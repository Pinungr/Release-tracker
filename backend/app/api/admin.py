"""Administrator endpoints. Every route below requires a valid admin session
(except login), and every mutation is written to the audit trail."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import LocalAuthProvider
from ..database import get_db
from ..models import (
    ACTIVE_STATUSES,
    AdminUser,
    BookingAudit,
    BookingStatus,
    DailySlotOverride,
    DeploymentBooking,
    DeploymentSlotConfiguration,
    Holiday,
    Tenant,
    User,
)
from ..schemas import (
    AdminLoginRequest,
    AdminSession,
    AuditEventOut,
    BookingCreate,
    BookingCreated,
    BookingDetail,
    BookingSummary,
    DailyOverrideIn,
    DailyOverrideOut,
    HolidayIn,
    HolidayOut,
    MoveBookingRequest,
    ReassignBookingRequest,
    SettingsOut,
    SettingsUpdate,
    SlotConfigOut,
    SlotConfigReplace,
    StatusUpdateRequest,
)
from ..security import AdminPrincipal, create_admin_token, require_admin, revoke_token, verify_secret
from ..security.ratelimit import enforce
from ..services import attachment_service, audit_service, booking_service, presenters
from ..services.booking_service import Actor, BusinessRuleError
from ..services.settings_service import get_app_settings, update_settings
from ..utils.dates import now_utc, today_local
from .deps import get_booking

router = APIRouter(prefix="/admin", tags=["admin"])

#: Statuses an administrator may set directly.
SETTABLE_STATUSES = {BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.CANCELLED}


def _actor(admin: AdminPrincipal) -> Actor:
    return Actor(is_admin=True, admin_username=admin.username)


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


@router.post("/login", response_model=AdminSession)
def login(request: Request, payload: AdminLoginRequest, db: Session = Depends(get_db)) -> AdminSession:
    enforce(request, "admin-login", limit=8, window_seconds=300)
    provider = LocalAuthProvider(
        lambda username: db.scalars(select(AdminUser).where(AdminUser.username == username)).first()
    )
    user = db.scalars(select(AdminUser).where(AdminUser.username == payload.username)).first()
    if user is None or not provider.authenticate(payload.username, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid administrator credentials.")
    user.last_login_at = now_utc()
    token, expires_in = create_admin_token(user.username)
    audit_service.record(
        db, event_type="ADMIN_LOGIN", actor_type="ADMIN", admin_username=user.username
    )
    db.commit()
    return AdminSession(
        access_token=token,
        expires_in=expires_in,
        username=user.username,
        display_name=user.display_name,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(admin: AdminPrincipal = Depends(require_admin)) -> None:
    revoke_token(admin.payload)


@router.get("/me", response_model=dict)
def me(admin: AdminPrincipal = Depends(require_admin)) -> dict:
    return {"username": admin.username, "role": "admin"}


@router.get("/tenants", response_model=list[dict])
def list_tenants(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    tenants = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    return [{"id": t.id, "name": t.name, "team_name": t.team_name, "is_active": t.is_active} for t in tenants]


@router.get("/users", response_model=list[dict])
def list_users(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    users = db.scalars(select(User).order_by(User.email)).all()
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "username": u.username,
            "email": u.email,
            "tenant_name": u.tenant.name if u.tenant else None,
            "role": u.role,
            "is_active": u.is_active,
        }
        for u in users
    ]


# --------------------------------------------------------------------------- #
# Settings & slot configuration
# --------------------------------------------------------------------------- #


@router.get("/settings", response_model=SettingsOut)
def read_settings(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> SettingsOut:
    return SettingsOut(**presenters.settings_out(db))


@router.put("/settings", response_model=SettingsOut)
def write_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> SettingsOut:
    before = presenters.settings_out(db)
    changes = payload.model_dump(exclude_none=True)
    if "mandatory_documents" in changes:
        changes["mandatory_documents"] = [c.value for c in payload.mandatory_documents or []]
    update_settings(db, changes)
    after = presenters.settings_out(db)
    old, new = audit_service.diff(before, after)
    if old:
        audit_service.record(
            db,
            event_type="SETTINGS_UPDATED",
            actor_type="ADMIN",
            admin_username=admin.username,
            old_values=old,
            new_values=new,
        )
    db.commit()
    return SettingsOut(**after)


@router.get("/slots", response_model=list[SlotConfigOut])
def read_slots(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> list[SlotConfigOut]:
    rows = db.scalars(
        select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
    ).all()
    return [SlotConfigOut.model_validate(r) for r in rows]


@router.put("/slots", response_model=list[SlotConfigOut])
def replace_slots(
    payload: SlotConfigReplace,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[SlotConfigOut]:
    """Replaces the whole grid. Slot numbers that still hold active bookings
    cannot be removed, so the board can never reference a missing slot."""
    incoming = {s.slot_number for s in payload.slots}
    active = set(
        db.scalars(
            select(DeploymentBooking.slot_number).where(
                DeploymentBooking.status.in_(ACTIVE_STATUSES),
                DeploymentBooking.deployment_date >= today_local(),
            )
        ).all()
    )
    missing = sorted(active - incoming)
    if missing:
        raise BusinessRuleError(
            "Cannot remove slot "
            + ", ".join(str(m) for m in missing)
            + " while upcoming deployments are booked in it."
        )

    before = [
        SlotConfigOut.model_validate(r).model_dump(mode="json")
        for r in db.scalars(
            select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
        ).all()
    ]
    db.execute(delete(DeploymentSlotConfiguration))
    for slot in payload.slots:
        db.add(DeploymentSlotConfiguration(**slot.model_dump()))
    db.flush()
    rows = db.scalars(
        select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
    ).all()
    audit_service.record(
        db,
        event_type="SLOT_CONFIG_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={"slots": before},
        new_values={"slots": [SlotConfigOut.model_validate(r).model_dump(mode="json") for r in rows]},
    )
    db.commit()
    return [SlotConfigOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- #
# Holidays
# --------------------------------------------------------------------------- #


@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[HolidayOut]:
    stmt = select(Holiday).order_by(Holiday.holiday_date)
    if year:
        stmt = stmt.where(
            Holiday.holiday_date >= date(year, 1, 1), Holiday.holiday_date <= date(year, 12, 31)
        )
    return [HolidayOut.model_validate(h) for h in db.scalars(stmt).all()]


@router.post("/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
def create_holiday(
    payload: HolidayIn,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> HolidayOut:
    holiday = Holiday(**payload.model_dump())
    db.add(holiday)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessRuleError(
            "A holiday already exists on that date.", status.HTTP_409_CONFLICT
        ) from None
    audit_service.record(
        db,
        event_type="HOLIDAY_CREATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values=payload.model_dump(mode="json"),
    )
    db.commit()
    return HolidayOut.model_validate(holiday)


@router.put("/holidays/{holiday_id}", response_model=HolidayOut)
def update_holiday(
    holiday_id: int,
    payload: HolidayIn,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> HolidayOut:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    before = HolidayOut.model_validate(holiday).model_dump(mode="json")
    for key, value in payload.model_dump().items():
        setattr(holiday, key, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessRuleError(
            "A holiday already exists on that date.", status.HTTP_409_CONFLICT
        ) from None
    audit_service.record(
        db,
        event_type="HOLIDAY_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=before,
        new_values=HolidayOut.model_validate(holiday).model_dump(mode="json"),
    )
    db.commit()
    return HolidayOut.model_validate(holiday)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    audit_service.record(
        db,
        event_type="HOLIDAY_DELETED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=HolidayOut.model_validate(holiday).model_dump(mode="json"),
    )
    db.delete(holiday)
    db.commit()


# --------------------------------------------------------------------------- #
# Per-day slot overrides
# --------------------------------------------------------------------------- #


@router.get("/overrides", response_model=list[DailyOverrideOut])
def list_overrides(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> list[DailyOverrideOut]:
    rows = db.scalars(select(DailySlotOverride).order_by(DailySlotOverride.override_date)).all()
    return [DailyOverrideOut.model_validate(r) for r in rows]


@router.put("/overrides", response_model=DailyOverrideOut)
def upsert_override(
    payload: DailyOverrideIn,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> DailyOverrideOut:
    row = db.scalars(
        select(DailySlotOverride).where(DailySlotOverride.override_date == payload.override_date)
    ).first()
    before = DailyOverrideOut.model_validate(row).model_dump(mode="json") if row else None
    if row is None:
        row = DailySlotOverride(**payload.model_dump())
        db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    db.flush()
    audit_service.record(
        db,
        event_type="DAILY_OVERRIDE_SET",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=before,
        new_values=DailyOverrideOut.model_validate(row).model_dump(mode="json"),
    )
    db.commit()
    return DailyOverrideOut.model_validate(row)


@router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_override(
    override_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    row = db.get(DailySlotOverride, override_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Override not found.")
    audit_service.record(
        db,
        event_type="DAILY_OVERRIDE_CLEARED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=DailyOverrideOut.model_validate(row).model_dump(mode="json"),
    )
    db.delete(row)
    db.commit()


# --------------------------------------------------------------------------- #
# Booking management
# --------------------------------------------------------------------------- #


@router.post("/bookings/emergency", response_model=BookingCreated, status_code=status.HTTP_201_CREATED)
def create_emergency_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingCreated:
    """Convenience alias for the emergency form; the generic POST /bookings
    works identically for an authenticated admin."""
    booking, token = booking_service.create_booking(db, payload, _actor(admin))
    if not booking.is_emergency:
        raise BusinessRuleError("The selected slot is not an emergency slot.")
    return BookingCreated(
        booking=presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True),
        manage_token=token,
        manage_url=f"/booking/manage/{token}",
        message=booking_service.success_message(db, booking),
    )


@router.get("/bookings/{booking_id}", response_model=BookingDetail)
def read_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True)


@router.post("/bookings/{booking_id}/move", response_model=BookingDetail)
def move_booking(
    payload: MoveBookingRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    from ..schemas import BookingUpdate
    from ..models import Technology

    update = BookingUpdate(
        tenant_name=booking.tenant_name,
        jira_change=booking.jira_change,
        jira_task=booking.jira_task,
        jira_url=booking.jira_url,
        environment=booking.environment,
        technology=Technology(booking.technology),
        requester_name=booking.requester_name,
        requester_email=booking.requester_email,
        requester_phone=booking.requester_phone,
        verifier_name=booking.verifier_name,
        verifier_email=booking.verifier_email,
        git_repository=booking.git_repository,
        implementation_summary=booking.implementation_summary,
        deployment_description=booking.deployment_description,
        additional_comments=booking.additional_comments,
        emergency_reason=booking.emergency_reason,
        emergency_approval_reference=booking.emergency_approval_reference,
        emergency_approver=booking.emergency_approver,
        business_justification=booking.business_justification,
        deployment_date=payload.deployment_date,
        slot_number=payload.slot_number,
        override_weekly_limit=True,
        override_reason=payload.override_reason,
    )
    booking = booking_service.update_booking(db, booking, update, _actor(admin))
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True)


@router.post("/bookings/{booking_id}/reassign", response_model=BookingDetail)
def reassign_booking(
    payload: ReassignBookingRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    before = audit_service.snapshot(booking)
    if payload.tenant_name:
        booking.tenant_name = payload.tenant_name
        booking.tenant_key = booking_service.tenant_key(payload.tenant_name)
    for field in ("requester_name", "requester_email", "verifier_name", "verifier_email"):
        value = getattr(payload, field)
        if value:
            setattr(booking, field, value)
    db.flush()
    old, new = audit_service.diff(before, audit_service.snapshot(booking))
    if old:
        audit_service.record(
            db,
            event_type="BOOKING_REASSIGNED",
            booking=booking,
            actor_type="ADMIN",
            admin_username=admin.username,
            override_reason=payload.override_reason,
            old_values=old,
            new_values=new,
        )
    db.commit()
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True)


@router.post("/bookings/{booking_id}/status", response_model=BookingDetail)
def set_status(
    payload: StatusUpdateRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    try:
        new_status = BookingStatus(payload.status)
    except ValueError:
        raise BusinessRuleError("Unknown booking status.") from None
    # LOCKED is derived from the freeze window, and the post-deployment
    # validation statuses are reserved for a future release, so neither can be
    # set here.
    if new_status not in SETTABLE_STATUSES:
        raise BusinessRuleError(
            "Only BOOKED, COMPLETED and CANCELLED can be set from the admin panel."
        )
    if new_status is BookingStatus.COMPLETED:
        # A deployment cannot be signed off with required paperwork missing,
        # unless an administrator records a reason for the exception.
        if not (payload.override_reason or "").strip():
            booking_service.assert_documents_complete(db, booking)
    old = booking.status
    booking.status = new_status.value
    if new_status is BookingStatus.CANCELLED and booking.cancelled_at is None:
        booking.cancelled_at = now_utc()
    db.flush()
    audit_service.record(
        db,
        event_type="BOOKING_STATUS_CHANGED",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        override_reason=payload.override_reason,
        old_values={"status": old},
        new_values={"status": booking.status},
    )
    db.commit()
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True)


@router.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def hard_delete_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    booking_id = booking.id
    booking_service.delete_booking(db, booking, _actor(admin))
    attachment_service.remove_booking_directory(booking_id)


@router.get("/bookings", response_model=list[BookingSummary])
def list_bookings(
    start: date | None = None,
    end: date | None = None,
    include_cancelled: bool = False,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[BookingSummary]:
    stmt = select(DeploymentBooking).order_by(
        DeploymentBooking.deployment_date.desc(), DeploymentBooking.slot_number
    )
    if start:
        stmt = stmt.where(DeploymentBooking.deployment_date >= start)
    if end:
        stmt = stmt.where(DeploymentBooking.deployment_date <= end)
    if not include_cancelled:
        stmt = stmt.where(DeploymentBooking.status.in_(ACTIVE_STATUSES))
    app_settings = get_app_settings(db)
    return [presenters.booking_summary(db, b, app_settings) for b in db.scalars(stmt.limit(500)).all()]


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


@router.get("/audit", response_model=list[AuditEventOut])
def read_audit(
    booking_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[AuditEventOut]:
    stmt = select(BookingAudit).order_by(BookingAudit.id.desc()).limit(limit)
    if booking_id:
        stmt = stmt.where(BookingAudit.booking_id == booking_id)
    return [presenters.audit_event_out(e) for e in db.scalars(stmt).all()]
