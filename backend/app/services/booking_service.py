"""Booking business rules.

This module is the single source of truth for:
  * normal slot existence / enablement / holiday blocking
  * emergency-change access (administrators only, queued per date)
  * the per-tenant weekly limit (and the audited admin override)
  * administrator-controlled manual slot freezes
  * document readiness

Ownership is decided by ``created_by_user_id`` against the authenticated
caller; the API layer never re-implements any of these rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_STATUSES,
    DOCUMENT_LABELS,
    BookingAssignment,
    BookingAttachment,
    BookingAudit,
    BookingStatus,
    DeploymentBooking,
    DocumentCategory,
    SlotFreeze,
    Tenant,
    User,
)
from ..schemas.booking import BookingCreate, BookingUpdate, DocumentReadiness, DocumentStatus
from ..utils.dates import format_day, format_time, is_deployment_weekday, now_utc, today_local, week_start
from . import audit_service, schedule_service
from .settings_service import AppSettings, get_app_settings


class BusinessRuleError(HTTPException):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=message)


def resolve_tenant(db: Session, tenant_id: int) -> Tenant:
    """Tenants come from the admin-managed master only.

    Scheduling never creates a tenant as a side effect, so a typo cannot
    silently fork a weekly quota into a brand new tenant row.
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise BusinessRuleError(
            "Select a valid tenant for this change record.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if not tenant.is_active:
        raise BusinessRuleError("The selected tenant is inactive.", status.HTTP_409_CONFLICT)
    return tenant


def next_booking_reference(db: Session, day: date) -> str:
    prefix = f"PDS-{day.strftime('%Y%m%d')}-"
    used = db.scalars(
        select(DeploymentBooking.booking_reference).where(
            DeploymentBooking.booking_reference.like(f"{prefix}%")
        )
    ).all()
    highest = 0
    for ref in used:
        tail = ref.rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:03d}"


# --------------------------------------------------------------------------- #
# Manual slot freeze
# --------------------------------------------------------------------------- #

# Automatic date freezing was intentionally removed. Administrators explicitly
# freeze/unfreeze individual normal slots. Past dates are still immutable for
# everyone, including administrators.
FREEZE_DEPLOYMENT_DATES = 0  # retained in the public settings payload for compatibility
PAST_READ_ONLY_MESSAGE = "Past deployment records are read-only and cannot be modified."
MANUAL_FREEZE_MESSAGE = "This deployment slot has been manually frozen by an administrator."


def is_past_deployment(day: date) -> bool:
    return day < today_local()


def assert_day_not_past(day: date) -> None:
    if is_past_deployment(day):
        raise BusinessRuleError(PAST_READ_ONLY_MESSAGE, status.HTTP_423_LOCKED)


def assert_booking_not_past(booking: DeploymentBooking) -> None:
    assert_day_not_past(booking.deployment_date)


def slot_freezes_between(db: Session, start: date, end: date) -> set[tuple[date, int]]:
    rows = db.scalars(
        select(SlotFreeze).where(SlotFreeze.freeze_date >= start, SlotFreeze.freeze_date <= end)
    ).all()
    return {(row.freeze_date, row.slot_number) for row in rows}


def is_slot_manually_frozen(db: Session, day: date, slot_number: int | None) -> bool:
    if slot_number is None:
        return False
    return db.scalar(
        select(SlotFreeze.id).where(
            SlotFreeze.freeze_date == day, SlotFreeze.slot_number == slot_number
        )
    ) is not None


def is_date_frozen_for_owner(db: Session, day: date) -> bool:
    """Compatibility helper. Dates are no longer automatically frozen."""
    return day < today_local()


def lock_deadline(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> None:
    """Compatibility shim: the scheduler no longer exposes a time-based deadline."""
    return None


def is_locked_for_owner(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> bool:
    if booking.deployment_date < today_local():
        return True
    if booking.is_emergency:
        return False
    if booking.status == BookingStatus.CANCELLED.value:
        return True
    return is_slot_manually_frozen(db, booking.deployment_date, booking.slot_number)


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


def document_readiness(booking: DeploymentBooking, app_settings: AppSettings) -> DocumentReadiness:
    counts: dict[str, int] = {}
    for att in booking.attachments:
        counts[att.category] = counts.get(att.category, 0) + 1

    mandatory = set(app_settings.mandatory_documents)
    items: list[DocumentStatus] = []
    for category in DocumentCategory:
        count = counts.get(category.value, 0)
        items.append(
            DocumentStatus(
                category=category,
                label=DOCUMENT_LABELS[category.value],
                required=category.value in mandatory,
                provided=count > 0,
                file_count=count,
            )
        )
    required_items = [i for i in items if i.required]
    provided_required = sum(1 for i in required_items if i.provided)
    total_required = len(required_items)
    percent = 100 if total_required == 0 else round(provided_required * 100 / total_required)
    return DocumentReadiness(
        provided_required=provided_required,
        total_required=total_required,
        percent=percent,
        complete=provided_required == total_required,
        missing_labels=[i.label for i in required_items if not i.provided],
        items=items,
    )


def assert_documents_complete(db: Session, booking: DeploymentBooking) -> None:
    readiness = document_readiness(booking, get_app_settings(db))
    if not readiness.complete:
        raise BusinessRuleError(
            "Required deployment document missing: " + ", ".join(readiness.missing_labels)
        )


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Actor:
    """Who is making the change."""

    is_admin: bool
    admin_username: str | None = None
    requester_email: str | None = None
    user_id: int | None = None

    @property
    def actor_type(self) -> str:
        return "ADMIN" if self.is_admin else "USER"


# --------------------------------------------------------------------------- #
# Slot / limit validation
# --------------------------------------------------------------------------- #


def weekly_normal_count(db: Session, tenant_id: int, any_day: date, *, exclude_id: int | None = None) -> int:
    sunday = week_start(any_day)
    thursday = sunday + timedelta(days=4)
    stmt = select(func.count(DeploymentBooking.id)).where(
        DeploymentBooking.tenant_id == tenant_id,
        DeploymentBooking.deployment_date >= sunday,
        DeploymentBooking.deployment_date <= thursday,
        DeploymentBooking.is_emergency.is_(False),
        DeploymentBooking.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id is not None:
        stmt = stmt.where(DeploymentBooking.id != exclude_id)
    return int(db.scalar(stmt) or 0)


def _validate_slot_target(
    db: Session,
    day: date,
    slot_number: int | None,
    actor: Actor,
    app_settings: AppSettings,
) -> schedule_service.ResolvedSlot:
    # Past dates are immutable historical records for everyone, including
    # administrators. Admins may still override future weekend/holiday/slot
    # restrictions, but they can never create or move data into the past.
    assert_day_not_past(day)
    if slot_number is None:
        raise BusinessRuleError("A normal deployment slot is required for this booking.")
    if not actor.is_admin:
        if not is_deployment_weekday(day):
            raise BusinessRuleError("Deployments can only be scheduled Sunday to Thursday.")
        if is_slot_manually_frozen(db, day, slot_number):
            raise BusinessRuleError(MANUAL_FREEZE_MESSAGE, status.HTTP_423_LOCKED)

    plan = schedule_service.resolve_day(db, day, app_settings=app_settings)
    slot = next((s for s in plan.slots if s.slot_number == slot_number), None)
    if slot is None:
        raise BusinessRuleError("The selected deployment slot does not exist.", status.HTTP_404_NOT_FOUND)
    if not actor.is_admin:
        if not slot.enabled:
            raise BusinessRuleError("That deployment slot is disabled for this date.")
        if slot.unavailable_reason:
            raise BusinessRuleError(slot.unavailable_reason)
    return slot


def _validate_weekly_limit(
    db: Session,
    *,
    tenant_id: int,
    tenant_name: str,
    day: date,
    is_emergency: bool,
    actor: Actor,
    app_settings: AppSettings,
    override: bool,
    exclude_id: int | None = None,
) -> bool:
    """Returns True when an admin override was actually applied."""
    if is_emergency:
        # Emergency bookings never count against the normal weekly limit.
        return False
    count = weekly_normal_count(db, tenant_id, day, exclude_id=exclude_id)
    if count < app_settings.weekly_booking_limit:
        return False
    # Administrators automatically bypass tenant weekly limits. The boolean
    # return is retained so the audit trail can record that a bypass happened;
    # no checkbox or manually-entered reason is required.
    if actor.is_admin:
        return True
    raise BusinessRuleError(
        f"Weekly booking limit reached. {tenant_name} already has "
        f"{count} deployment slot{'s' if count != 1 else ''} booked for this week.",
        status.HTTP_409_CONFLICT,
    )


def _validate_emergency_fields(payload: BookingCreate | BookingUpdate, is_emergency: bool) -> None:
    if not is_emergency:
        return
    if not (payload.emergency_reason or "").strip():
        raise BusinessRuleError("Emergency Reason is required for an emergency change.")
    if not (payload.business_justification or "").strip():
        raise BusinessRuleError("Business Justification is required for an emergency change.")



# --------------------------------------------------------------------------- #
# Create / update / cancel
# --------------------------------------------------------------------------- #


SLOT_TAKEN_MESSAGE = (
    "This slot has just been booked by another user. Please select another available slot."
)


def _slot_taken(db: Session, day: date, slot_number: int | None, exclude_id: int | None = None) -> bool:
    # Emergency changes carry no slot number. Without this guard the query
    # below would compile to `slot_number IS NULL` and every emergency change
    # on the date would look like a slot conflict.
    if slot_number is None:
        return False
    stmt = select(DeploymentBooking.id).where(
        DeploymentBooking.deployment_date == day,
        DeploymentBooking.slot_number == slot_number,
        DeploymentBooking.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id is not None:
        stmt = stmt.where(DeploymentBooking.id != exclude_id)
    return db.scalar(stmt) is not None


def _flush_new_booking(db: Session, booking: DeploymentBooking, attempts: int = 5) -> None:
    """Insert the booking, distinguishing the two unique constraints it can hit.

    A clash on (deployment_date, slot_number) means somebody else won the slot
    and is terminal. A clash on booking_reference only means two requests
    picked the same sequence number in the same instant, so the reference is
    regenerated and the insert retried.
    """
    for _ in range(attempts):
        try:
            db.flush()
            return
        except IntegrityError:
            db.rollback()
            if _slot_taken(db, booking.deployment_date, booking.slot_number):
                raise BusinessRuleError(SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT) from None
            booking.booking_reference = next_booking_reference(db, booking.deployment_date)
            db.add(booking)
    raise BusinessRuleError(
        "The scheduler is busy right now. Please try that booking again.",
        status.HTTP_409_CONFLICT,
    )


def create_booking(
    db: Session, payload: BookingCreate, actor: Actor, *, commit: bool = True
) -> DeploymentBooking:
    app_settings = get_app_settings(db)
    tenant = resolve_tenant(db, payload.tenant_id)
    assert_day_not_past(payload.deployment_date)
    if payload.is_emergency:
        if not actor.is_admin:
            raise BusinessRuleError("Only administrators can create emergency changes.", status.HTTP_403_FORBIDDEN)
        # Emergency changes are explicitly an administrator capability. Date,
        # holiday, weekend and per-day emergency switches do not block admins.
        is_emergency = True
    else:
        _validate_slot_target(db, payload.deployment_date, payload.slot_number, actor, app_settings)
        is_emergency = False
    _validate_emergency_fields(payload, is_emergency)

    override_applied = _validate_weekly_limit(
        db,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        day=payload.deployment_date,
        is_emergency=is_emergency,
        actor=actor,
        app_settings=app_settings,
        override=payload.override_weekly_limit,
    )
    override_reason = None
    if override_applied:
        override_reason = (payload.override_reason or "").strip() or (
            "Administrator automatic override: tenant weekly booking limit."
        )

    booking = DeploymentBooking(
        booking_reference=next_booking_reference(db, payload.deployment_date),
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        created_by_user_id=actor.user_id,
        deployment_date=payload.deployment_date,
        slot_number=None if is_emergency else payload.slot_number,
        jira_number=payload.jira_number,
        jira_url=payload.jira_url,
        environment=payload.environment or "PROD",
        technology=payload.technology.value,
        requester_name=payload.requester_name,
        requester_email=str(payload.requester_email) if payload.requester_email else "",
        requester_phone=payload.requester_phone or None,
        verifier_name=payload.verifier_name,
        verifier_email=str(payload.verifier_email) if payload.verifier_email else "",
        git_repository=payload.git_repository,
        implementation_summary=payload.implementation_summary or "",
        deployment_description=payload.deployment_description,
        additional_comments=payload.additional_comments or None,
        status=BookingStatus.BOOKED.value,
        is_emergency=is_emergency,
        emergency_reason=payload.emergency_reason or None,
        emergency_approval_reference=payload.emergency_approval_reference or None,
        emergency_approver=payload.emergency_approver or None,
        business_justification=payload.business_justification or None,
    )
    db.add(booking)
    _flush_new_booking(db, booking)

    audit_service.record(
        db,
        event_type="EMERGENCY_BOOKING_CREATED" if is_emergency else "BOOKING_CREATED",
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        override_reason=override_reason or None,
        new_values=audit_service.snapshot(booking),
    )
    if commit:
        db.commit()
        db.refresh(booking)
    else:
        db.flush()
    return booking


def update_booking(
    db: Session,
    booking: DeploymentBooking,
    payload: BookingUpdate,
    actor: Actor,
) -> DeploymentBooking:
    app_settings = get_app_settings(db)
    assert_booking_not_past(booking)
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("This booking has been cancelled and can no longer be edited.")

    override_reason: str | None = None
    if not actor.is_admin:
        if is_locked_for_owner(db, booking, app_settings):
            raise BusinessRuleError(
                MANUAL_FREEZE_MESSAGE + " Contact an administrator for assistance.",
                status.HTTP_423_LOCKED,
            )
        if booking.is_emergency:
            raise BusinessRuleError(
                "Emergency change records can only be modified by an administrator.",
                status.HTTP_403_FORBIDDEN,
            )
    elif is_locked_for_owner(db, booking, app_settings):
        override_reason = (payload.override_reason or "").strip() or (
            "Administrator override: manually frozen deployment slot."
        )

    before = audit_service.snapshot(booking)

    new_day = payload.deployment_date or booking.deployment_date
    assert_day_not_past(new_day)
    new_slot_number = payload.slot_number or booking.slot_number
    moved = (new_day, new_slot_number) != (booking.deployment_date, booking.slot_number)
    if moved and not booking.is_emergency:
        _validate_slot_target(db, new_day, new_slot_number, actor, app_settings)

    tenant = resolve_tenant(db, payload.tenant_id)
    if not booking.is_emergency and (moved or tenant.id != booking.tenant_id):
        applied = _validate_weekly_limit(
            db,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            day=new_day,
            is_emergency=False,
            actor=actor,
            app_settings=app_settings,
            override=payload.override_weekly_limit,
            exclude_id=booking.id,
        )
        if applied:
            override_reason = (payload.override_reason or "").strip() or (
                "Administrator automatic override: tenant weekly booking limit."
            )

    _validate_emergency_fields(payload, booking.is_emergency)

    booking.tenant_id = tenant.id
    booking.tenant_name = tenant.name
    booking.deployment_date = new_day
    booking.slot_number = None if booking.is_emergency else new_slot_number
    booking.jira_number = payload.jira_number
    booking.jira_url = payload.jira_url
    booking.environment = payload.environment or "PROD"
    booking.technology = payload.technology.value
    booking.requester_name = payload.requester_name
    booking.requester_email = str(payload.requester_email) if payload.requester_email else ""
    booking.requester_phone = payload.requester_phone or None
    booking.verifier_name = payload.verifier_name
    booking.verifier_email = str(payload.verifier_email) if payload.verifier_email else ""
    booking.git_repository = payload.git_repository
    booking.implementation_summary = payload.implementation_summary or ""
    booking.deployment_description = payload.deployment_description
    booking.additional_comments = payload.additional_comments or None
    if booking.is_emergency:
        booking.emergency_reason = payload.emergency_reason or None
        booking.emergency_approval_reference = payload.emergency_approval_reference or None
        booking.emergency_approver = payload.emergency_approver or None
        booking.business_justification = payload.business_justification or None

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessRuleError(SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT) from None

    old_values, new_values = audit_service.diff(before, audit_service.snapshot(booking))
    if old_values:
        audit_service.record(
            db,
            event_type="SLOT_CHANGED" if moved else "BOOKING_EDITED",
            booking=booking,
            actor_type=actor.actor_type,
            requester_email=booking.requester_email,
            admin_username=actor.admin_username,
            override_reason=override_reason or None,
            old_values=old_values,
            new_values=new_values,
        )
    db.commit()
    return booking


def cancel_booking(
    db: Session, booking: DeploymentBooking, actor: Actor, override_reason: str | None = None
) -> DeploymentBooking:
    app_settings = get_app_settings(db)
    assert_booking_not_past(booking)
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("This booking is already cancelled.")

    reason: str | None = None
    if not actor.is_admin:
        if is_locked_for_owner(db, booking, app_settings):
            raise BusinessRuleError(
                MANUAL_FREEZE_MESSAGE + " Contact an administrator for assistance.",
                status.HTTP_423_LOCKED,
            )
        if booking.is_emergency:
            raise BusinessRuleError(
                "Emergency change records can only be cancelled by an administrator.",
                status.HTTP_403_FORBIDDEN,
            )
    elif is_locked_for_owner(db, booking, app_settings):
        reason = (override_reason or "").strip() or (
            "Administrator override: manually frozen deployment slot."
        )

    before = audit_service.snapshot(booking)
    booking.status = BookingStatus.CANCELLED.value
    booking.cancelled_at = now_utc()
    db.flush()
    audit_service.record(
        db,
        event_type="BOOKING_CANCELLED",
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        override_reason=reason or None,
        old_values={"status": before["status"]},
        new_values={"status": booking.status},
    )
    db.commit()
    return booking


def delete_booking(db: Session, booking: DeploymentBooking, actor: Actor) -> None:
    """Hard delete a non-historical booking while retaining its audit trail."""
    assert_booking_not_past(booking)
    booking_id = booking.id
    reference = booking.booking_reference
    snapshot = audit_service.snapshot(booking) | {"booking_reference": reference}

    # Detach historical events before deleting the booking. This preserves
    # audit rows even on legacy databases whose FK was originally CASCADE.
    historical = list(db.scalars(select(BookingAudit).where(BookingAudit.booking_id == booking_id)).all())
    for event in historical:
        event.booking_id = None
        if not event.booking_reference:
            event.booking_reference = reference
    db.flush()

    deleted_event = audit_service.record(
        db,
        event_type="BOOKING_DELETED",
        booking=None,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        old_values=snapshot,
    )
    deleted_event.booking_reference = reference
    db.delete(booking)
    db.commit()


def assign_users_to_booking(
    db: Session, booking: DeploymentBooking, user_ids: list[int], actor: Actor
) -> DeploymentBooking:
    """Replace the RM assignment list for a booking. Administrator only."""
    if not actor.is_admin:
        raise BusinessRuleError("Only administrators can assign RM users.", status.HTTP_403_FORBIDDEN)
    assert_booking_not_past(booking)
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("A cancelled booking cannot be assigned.")

    unique_ids = list(dict.fromkeys(user_ids))
    users = list(
        db.scalars(
            select(User).where(
                User.id.in_(unique_ids),
                User.is_active.is_(True),
                User.role == "TENANT_USER",
            )
        ).all()
    )
    found = {u.id for u in users}
    missing = [uid for uid in unique_ids if uid not in found]
    if missing:
        raise BusinessRuleError(
            "One or more selected RM users are inactive, invalid, or not assignable.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if booking.created_by_user_id in found:
        raise BusinessRuleError(
            "The booking owner cannot also be assigned as an RM user.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    before_ids = [a.user_id for a in booking.assignments]
    booking.assignments.clear()
    db.flush()
    for uid in unique_ids:
        booking.assignments.append(
            BookingAssignment(booking_id=booking.id, user_id=uid, assigned_by_user_id=actor.user_id)
        )
    db.flush()
    audit_service.record(
        db,
        event_type="RM_USERS_ASSIGNED",
        booking=booking,
        actor_type=actor.actor_type,
        admin_username=actor.admin_username,
        old_values={"assigned_user_ids": before_ids},
        new_values={"assigned_user_ids": unique_ids},
    )
    db.commit()
    db.refresh(booking)
    return booking


def user_is_assigned(booking: DeploymentBooking, user_id: int) -> bool:
    return any(a.user_id == user_id for a in booking.assignments)


def start_work(
    db: Session, booking: DeploymentBooking, change_number: str, actor: Actor
) -> DeploymentBooking:
    """Assigned RM user supplies the separate Change No. and starts work."""
    assert_booking_not_past(booking)
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("A cancelled booking cannot be started.")
    if not actor.is_admin:
        if actor.user_id is None or not user_is_assigned(booking, actor.user_id):
            raise BusinessRuleError("Only an assigned RM user can start work on this booking.", status.HTTP_403_FORBIDDEN)
    before = {
        "change_number": booking.change_number,
        "status": booking.status,
        "work_started_by_user_id": booking.work_started_by_user_id,
    }
    booking.change_number = change_number.strip()
    booking.work_started_by_user_id = actor.user_id
    booking.work_started_at = now_utc()
    if booking.status == BookingStatus.BOOKED.value:
        booking.status = BookingStatus.IN_PROGRESS.value
    db.flush()
    audit_service.record(
        db,
        event_type="WORK_STARTED" if before["change_number"] is None else "CHANGE_NUMBER_UPDATED",
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=actor.requester_email,
        admin_username=actor.admin_username,
        old_values=before,
        new_values={
            "change_number": booking.change_number,
            "status": booking.status,
            "work_started_by_user_id": booking.work_started_by_user_id,
        },
    )
    db.commit()
    return booking


def slot_labels(db: Session, booking: DeploymentBooking) -> tuple[str, str]:
    if booking.is_emergency or booking.slot_number is None:
        return "Emergency queue", ""
    slot = schedule_service.find_slot(db, booking.deployment_date, booking.slot_number)
    if slot is None:
        return f"Slot {booking.slot_number}", ""
    return slot.name, f"{format_time(slot.start_time)} - {format_time(slot.end_time)}"


def success_message(db: Session, booking: DeploymentBooking) -> str:
    name, times = slot_labels(db, booking)
    return (
        ("Emergency change queued successfully.\n" if booking.is_emergency else "Deployment slot booked successfully.\n")
        + f"Booking Reference: {booking.booking_reference}\n"
        f"{booking.deployment_date.strftime('%A')} {format_day(booking.deployment_date)}\n"
        f"{name} {times}\n"
        f"Tenant: {booking.tenant_name}\n"
        "Your authenticated account owns this change record and controls future edits."
    )


def attachment_of(booking: DeploymentBooking, attachment_id: int) -> BookingAttachment | None:
    return next((a for a in booking.attachments if a.id == attachment_id), None)
