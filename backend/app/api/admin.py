"""Administrator endpoints.

Every route requires an authenticated account whose stored role is ADMIN
(there is no separate administrator login), and every mutation is written
to the audit trail.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ACTIVE_STATUSES,
    BookingAudit,
    BookingStatus,
    DailySlotOverride,
    DeploymentBooking,
    DeploymentSlotConfiguration,
    Holiday,
    SlotFreeze,
    Tenant,
    User,
)
from ..schemas import (
    AssignUsersRequest,
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
    SlotFreezeOut,
    SlotFreezeRequest,
    StatusUpdateRequest,
)
from ..security import (
    AdminPrincipal,
    hash_secret,
    require_admin,
)
from ..services import attachment_service, audit_service, booking_service, presenters, schedule_service
from ..services.booking_service import Actor, BusinessRuleError
from ..services.settings_service import get_app_settings, update_settings
from ..utils.dates import now_utc, today_local
from .deps import get_booking

router = APIRouter(prefix="/admin", tags=["admin"])

#: Statuses an administrator may set directly.
SETTABLE_STATUSES = {BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.CANCELLED}


def _actor(admin: AdminPrincipal) -> Actor:
    return Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)


def _tenant_weekly_limit(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weekly_booking_limit must be between 1 and 25, or blank for the global default.",
        ) from None
    if not 1 <= parsed <= 25:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weekly_booking_limit must be between 1 and 25, or blank for the global default.",
        )
    return parsed


def _assert_not_last_active_admin(db: Session, target: User, admin: AdminPrincipal) -> None:
    """Refuse a demotion/deactivation that would leave nobody able to administer."""
    if target.role != "ADMIN" or not target.is_active:
        return
    remaining = db.scalar(
        select(func.count(User.id)).where(
            User.role == "ADMIN",
            User.is_active.is_(True),
            User.id != target.id,
        )
    )
    if not remaining:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the only active administrator. Promote another account first.",
        )


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

@router.get("/me", response_model=dict)
def me(admin: AdminPrincipal = Depends(require_admin)) -> dict:
    return {"username": admin.username, "role": "admin"}


@router.get("/tenants", response_model=list[dict])
def list_tenants(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    tenants = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "tenant_code": t.tenant_code,
            "description": t.description,
            "weekly_booking_limit": t.weekly_booking_limit,
            "is_active": t.is_active,
        }
        for t in tenants
    ]


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    name = str(payload.get("name", "")).strip()
    code = str(payload.get("tenant_code", "")).strip().upper()
    if not name or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tenant name and tenant code are required.")
    if db.scalars(select(Tenant).where((Tenant.name == name) | (Tenant.tenant_code == code))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant name or code already exists.")
    weekly_limit = _tenant_weekly_limit(payload.get("weekly_booking_limit"))
    tenant = Tenant(
        name=name,
        tenant_code=code,
        description=payload.get("description"),
        weekly_booking_limit=weekly_limit,
        is_active=True,
    )
    db.add(tenant)
    db.flush()
    audit_service.record(
        db,
        event_type="TENANT_CREATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values={
            "tenant_id": tenant.id,
            "name": tenant.name,
            "tenant_code": tenant.tenant_code,
            "weekly_booking_limit": tenant.weekly_booking_limit,
        },
    )
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.put("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    name = str(payload.get("name", tenant.name)).strip()
    code = str(payload.get("tenant_code", tenant.tenant_code or "")).strip().upper()
    duplicate = db.scalars(
        select(Tenant).where(
            Tenant.id != tenant_id,
            (Tenant.name == name) | (Tenant.tenant_code == code),
        )
    ).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant name or code already exists.")
    tenant.name = name
    tenant.tenant_code = code or None
    tenant.description = payload.get("description")
    if "weekly_booking_limit" in payload:
        tenant.weekly_booking_limit = _tenant_weekly_limit(payload.get("weekly_booking_limit"))
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.patch("/tenants/{tenant_id}/status")
def update_tenant_status(
    tenant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    if not isinstance(payload.get("is_active"), bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "is_active must be a boolean value.")
    tenant.is_active = payload["is_active"]
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.get("/users", response_model=list[dict])
def list_users(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
    search: str | None = Query(default=None),
) -> list[dict]:
    stmt = select(User)
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            (User.username.ilike(q))
            | (User.email.ilike(q))
            | (User.full_name.ilike(q))
        )
    users = db.scalars(stmt.order_by(User.email)).all()
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "must_change_password": u.must_change_password,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    new_password = str(payload.get("new_password", ""))
    confirm_new_password = str(payload.get("confirm_new_password", ""))
    if new_password != confirm_new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password and confirmation do not match.")
    if len(new_password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 8 characters long.")

    user.password_hash = hash_secret(new_password)
    user.must_change_password = True
    # Immediately revoke all previously issued JWTs for this account. This
    # value is stored in the database, so the invalidation survives restarts.
    user.token_version += 1
    audit_service.record(
        db,
        event_type="PASSWORD_RESET_BY_ADMIN",
        actor_type="ADMIN",
        admin_username=admin.username,
        requester_email=user.email,
        old_values={"user_id": user.id, "username": user.username, "email": user.email},
        new_values={"user_id": user.id, "username": user.username, "email": user.email},
    )
    db.commit()
    return {"message": "Credential updated successfully.", "user_id": user.id, "username": user.username}


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    is_active = payload.get("is_active")
    if not isinstance(is_active, bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "is_active must be a boolean value.")
    if not is_active:
        _assert_not_last_active_admin(db, user, admin)
    user.is_active = is_active
    audit_service.record(
        db,
        event_type="USER_STATUS_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        requester_email=user.email,
        old_values={"is_active": not is_active},
        new_values={"is_active": is_active},
    )
    db.commit()
    return {"message": "User status updated.", "user_id": user.id, "is_active": user.is_active}


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    role = str(payload.get("role", "")).strip().upper()
    if role not in {"ADMIN", "TENANT_USER"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be ADMIN or TENANT_USER.")
    if role != "ADMIN":
        _assert_not_last_active_admin(db, user, admin)
    previous = user.role
    user.role = role
    audit_service.record(
        db,
        event_type="USER_ROLE_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        requester_email=user.email,
        old_values={"role": previous},
        new_values={"role": user.role},
    )
    db.commit()
    return {"message": "Role updated.", "user_id": user.id, "role": user.role}


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
    booking = booking_service.create_booking(
        db,
        payload.model_copy(update={"is_emergency": True, "slot_number": None}),
        _actor(admin),
    )
    return BookingCreated(
        booking=presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True),
        message=booking_service.success_message(db, booking),
    )


@router.get("/bookings/{booking_id}", response_model=BookingDetail)
def read_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True)


@router.post("/bookings/{booking_id}/assign-users", response_model=BookingDetail)
def assign_booking_users(
    payload: AssignUsersRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    updated = booking_service.assign_users_to_booking(db, booking, payload.user_ids, _actor(admin))
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=True)


@router.post("/bookings/{booking_id}/move", response_model=BookingDetail)
def move_booking(
    payload: MoveBookingRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    from ..schemas import BookingUpdate
    from ..models import Technology

    if not booking.is_emergency and payload.slot_number is None:
        raise BusinessRuleError("A normal deployment slot is required when moving this booking.")

    update = BookingUpdate(
        tenant_id=booking.tenant_id,
        jira_number=booking.jira_number,
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
    booking_service.assert_booking_not_past(booking)
    before = audit_service.snapshot(booking)
    if payload.tenant_id is not None:
        tenant = booking_service.resolve_tenant(db, payload.tenant_id)
        booking.tenant_id = tenant.id
        booking.tenant_name = tenant.name
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
    booking_service.assert_booking_not_past(booking)
    try:
        new_status = BookingStatus(payload.status)
    except ValueError:
        raise BusinessRuleError("Unknown booking status.") from None
    # LOCKED is derived from manual slot freezing, and the post-deployment
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
# Manual slot freeze
# --------------------------------------------------------------------------- #


def _booking_in_slot(db: Session, day: date, slot_number: int) -> DeploymentBooking | None:
    return db.scalars(
        select(DeploymentBooking).where(
            DeploymentBooking.deployment_date == day,
            DeploymentBooking.slot_number == slot_number,
            DeploymentBooking.is_emergency.is_(False),
            DeploymentBooking.status.in_(ACTIVE_STATUSES),
        )
    ).first()


@router.post("/slot-freezes", response_model=SlotFreezeOut)
def freeze_slot(
    payload: SlotFreezeRequest,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> SlotFreezeOut:
    booking_service.assert_day_not_past(payload.freeze_date)
    if schedule_service.find_slot(db, payload.freeze_date, payload.slot_number) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The selected deployment slot does not exist.")

    row = db.scalars(
        select(SlotFreeze).where(
            SlotFreeze.freeze_date == payload.freeze_date,
            SlotFreeze.slot_number == payload.slot_number,
        )
    ).first()
    if row is None:
        row = SlotFreeze(
            freeze_date=payload.freeze_date,
            slot_number=payload.slot_number,
            created_by_user_id=admin.user_id,
            note=payload.note or None,
        )
        db.add(row)
    else:
        row.note = payload.note or row.note
        row.created_by_user_id = admin.user_id

    db.flush()
    booking = _booking_in_slot(db, payload.freeze_date, payload.slot_number)
    audit_service.record(
        db,
        event_type="SLOT_MANUALLY_FROZEN",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values={
            "deployment_date": payload.freeze_date,
            "slot_number": payload.slot_number,
            "note": row.note,
        },
    )
    db.commit()
    return SlotFreezeOut.model_validate(row)


@router.delete("/slot-freezes/{freeze_date}/{slot_number}", status_code=status.HTTP_204_NO_CONTENT)
def unfreeze_slot(
    freeze_date: date,
    slot_number: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    booking_service.assert_day_not_past(freeze_date)
    row = db.scalars(
        select(SlotFreeze).where(
            SlotFreeze.freeze_date == freeze_date, SlotFreeze.slot_number == slot_number
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This slot is not frozen.")
    booking = _booking_in_slot(db, freeze_date, slot_number)
    audit_service.record(
        db,
        event_type="SLOT_MANUALLY_UNFROZEN",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={
            "deployment_date": freeze_date,
            "slot_number": slot_number,
            "note": row.note,
        },
    )
    db.delete(row)
    db.commit()


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
