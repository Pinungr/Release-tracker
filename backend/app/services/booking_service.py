"""Booking business rules.

This module is the single source of truth for:
  * normal slot existence / enablement / holiday blocking
  * emergency-change access (administrators only, queued per date)
  * per-tenant weekly limits with a global fallback (and audited admin override)
  * protected past/current scheduling, with recent append-only document follow-up
  * the automatic upcoming-date lock, Admin/RM unlock overrides and manual slot freezes
  * document readiness
  * who may modify a schedule (``schedule_actor`` / ``schedule_permissions``)

A schedule may be modified by Admins/Release Managers, its original
scheduler, any member of its tenant group and its explicit collaborators;
Management is read-only. The API layer never re-implements any of these rules.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_STATUSES,
    AutomaticLockOverride,
    BookingAssignment,
    BookingCollaborator,
    BookingAttachment,
    BookingAudit,
    BookingStatus,
    AccessGroup,
    GroupMembership,
    GroupType,
    DeploymentBooking,
    DocumentType,
    SlotFreeze,
    Tenant,
    User,
)
from ..schemas.booking import BookingCreate, BookingUpdate, DocumentReadiness, DocumentStatus
from ..utils.dates import format_day, format_time, is_deployment_weekday, now_utc, today_local, week_start
from . import audit_service, document_type_service, schedule_service, group_service
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
    # One sequence across dates; retained audits prevent reuse after deletion.
    prefix = "pds-"
    used = db.scalars(
        select(DeploymentBooking.booking_reference).where(
            DeploymentBooking.booking_reference.like(f"{prefix}%")
        )
    ).all()
    # References remain reserved after permanent deletion through retained audit rows.
    used += db.scalars(select(BookingAudit.booking_reference).where(
        BookingAudit.booking_reference.like(f"{prefix}%")
    ).distinct()).all()
    highest = 0
    for ref in used:
        tail = ref[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:03d}"


# --------------------------------------------------------------------------- #
# Date / slot freeze rules
# --------------------------------------------------------------------------- #

PAST_CURRENT_READ_ONLY_MESSAGE = (
    "Scheduling on past and current deployment dates is read-only. "
    "Recent dates may be unlocked for additional documents only."
)
FOLLOWUP_DAYS = 7
AUTOMATIC_FREEZE_MESSAGE = (
    "This deployment date is inside the configured upcoming-date freeze window."
)
MANUAL_FREEZE_MESSAGE = "This deployment slot has been manually frozen by an administrator."


def is_current_or_past_deployment(day: date) -> bool:
    return day <= today_local()


def assert_day_not_past(day: date) -> None:
    """Compatibility name: scheduling on past *and current* dates is protected."""
    if is_current_or_past_deployment(day):
        raise BusinessRuleError(PAST_CURRENT_READ_ONLY_MESSAGE, status.HTTP_423_LOCKED)


def assert_booking_not_past(booking: DeploymentBooking) -> None:
    assert_day_not_past(booking.deployment_date)


def automatic_frozen_dates(
    db: Session, app_settings: AppSettings | None = None
) -> set[date]:
    """Return today plus the configured number of upcoming deployment dates.

    Friday/Saturday and full-day holidays are skipped when counting upcoming
    dates. This keeps a value of ``2`` aligned with the next two dates on which
    a normal production deployment could otherwise be scheduled.
    """
    app_settings = app_settings or get_app_settings(db)
    today = today_local()
    frozen = {today}
    remaining = app_settings.booking_freeze_dates
    if remaining <= 0:
        return frozen

    cursor = today + timedelta(days=1)
    # 25 configured deployment dates fit comfortably inside this guard even
    # with weekends and holidays; the guard prevents accidental endless loops.
    guard = 0
    while remaining > 0 and guard < 370:
        if is_deployment_weekday(cursor):
            plan = schedule_service.resolve_day(db, cursor, app_settings=app_settings)
            if not (plan.holiday is not None and plan.holiday.is_full_day):
                frozen.add(cursor)
                remaining -= 1
        cursor += timedelta(days=1)
        guard += 1
    return frozen


def is_date_automatically_frozen(
    db: Session, day: date, app_settings: AppSettings | None = None
) -> bool:
    if day <= today_local():
        return True
    return day in automatic_frozen_dates(db, app_settings)


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


def lock_overrides_between(db: Session, start: date, end: date) -> set[tuple[date, int | None]]:
    rows = db.scalars(
        select(AutomaticLockOverride).where(
            AutomaticLockOverride.override_date >= start, AutomaticLockOverride.override_date <= end
        )
    ).all()
    return {(row.override_date, row.slot_number) for row in rows}


def override_applies(overrides: set[tuple[date, int | None]], day: date, slot_number: int | None) -> bool:
    """A date-wide override covers every slot; a slot override covers only that slot."""
    return (day, None) in overrides or (slot_number is not None and (day, slot_number) in overrides)


def has_unlock_override(db: Session, day: date, slot_number: int | None) -> bool:
    stmt = select(AutomaticLockOverride.id).where(AutomaticLockOverride.override_date == day)
    if slot_number is None:
        stmt = stmt.where(AutomaticLockOverride.slot_number.is_(None))
    else:
        stmt = stmt.where(
            (AutomaticLockOverride.slot_number.is_(None)) | (AutomaticLockOverride.slot_number == slot_number)
        )
    return db.scalar(stmt.limit(1)) is not None


def is_schedule_locked(
    db: Session,
    day: date,
    slot_number: int | None,
    app_settings: AppSettings | None = None,
    *,
    frozen_dates: set[date] | None = None,
    overrides: set[tuple[date, int | None]] | None = None,
) -> bool:
    """Automatic Lock, after any Admin/RM unlock override.

    Scheduling on past and current dates is protected regardless of upload
    unlocks. Inside the automatic upcoming-date window a date or slot is
    locked unless an administrator explicitly unlocked it. Manual Freeze is a
    separate control and is not considered here.
    """
    if day <= today_local():
        return True
    if frozen_dates is None:
        frozen_dates = automatic_frozen_dates(db, app_settings)
    if day not in frozen_dates:
        return False
    if overrides is not None:
        return not override_applies(overrides, day, slot_number)
    return not has_unlock_override(db, day, slot_number)


def is_lock_overridden(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> bool:
    """True while an Admin/RM unlock is what keeps this booking editable."""
    day = booking.deployment_date
    slot = None if booking.is_emergency else booking.slot_number
    return (
        day > today_local()
        and is_date_automatically_frozen(db, day, app_settings)
        and has_unlock_override(db, day, slot)
    )


def booking_lock_reason(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> str:
    """The single derivation of a record's date/lock/freeze state.

    Display (``lock_reason``) and every write-permission check read this, so
    the UI and the API can never disagree about why a record is locked.
    """
    if booking.deployment_date < today_local():
        return "PAST_DATE"
    if booking.deployment_date == today_local():
        return "CURRENT_DATE"
    slot = None if booking.is_emergency else booking.slot_number
    if is_schedule_locked(db, booking.deployment_date, slot, app_settings):
        return "AUTOMATIC_DATE_FREEZE"
    if is_slot_manually_frozen(db, booking.deployment_date, booking.slot_number):
        return "MANUAL_SLOT_FREEZE"
    return "NONE"


CANCELLED_READ_ONLY_MESSAGE = "This booking has been cancelled and can no longer be modified."
COMPLETED_READ_ONLY_MESSAGE = (
    "This schedule is completed/closed. Only the Owner or a Release Manager can change it."
)


def owner_lock_reason(
    db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None
) -> str | None:
    """Why a non-admin (scheduler, tenant member, collaborator) may not change this record."""
    state = booking_lock_reason(db, booking, app_settings)
    if state in {"PAST_DATE", "CURRENT_DATE"}:
        return PAST_CURRENT_READ_ONLY_MESSAGE
    if booking.status == BookingStatus.CANCELLED.value:
        return CANCELLED_READ_ONLY_MESSAGE
    return {"AUTOMATIC_DATE_FREEZE": AUTOMATIC_FREEZE_MESSAGE, "MANUAL_SLOT_FREEZE": MANUAL_FREEZE_MESSAGE}.get(state)


def is_locked_for_owner(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> bool:
    return owner_lock_reason(db, booking, app_settings) is not None


def schedule_restriction(
    db: Session, booking: DeploymentBooking, actor: "Actor", app_settings: AppSettings | None = None
) -> BusinessRuleError | None:
    """Record-state rules applied after the caller's access was established.

    One place answers "is this schedule editable right now for this caller":
    past/current dates, cancellation, completion, the Automatic Lock (unless
    an Admin/RM unlocked it), Manual Freeze and the emergency queue.
    Administrators may still act on a manually frozen slot (audited as an
    override) and on a completed record. Scheduling changes inside the Automatic
    Lock require an unlock; closure and append-only follow-up have separate rules.
    """
    app_settings = app_settings or get_app_settings(db)
    state = booking_lock_reason(db, booking, app_settings)
    if actor.is_admin:
        if state in {"PAST_DATE", "CURRENT_DATE"}:
            return BusinessRuleError(PAST_CURRENT_READ_ONLY_MESSAGE, status.HTTP_423_LOCKED)
        if booking.status == BookingStatus.CANCELLED.value:
            return BusinessRuleError(CANCELLED_READ_ONLY_MESSAGE)
        if state == "AUTOMATIC_DATE_FREEZE":
            return BusinessRuleError(
                AUTOMATIC_FREEZE_MESSAGE + " Unlock the automatic lock first.", status.HTTP_423_LOCKED
            )
        return None
    reason = owner_lock_reason(db, booking, app_settings)
    if reason:
        if booking.status == BookingStatus.CANCELLED.value:
            return BusinessRuleError(reason)
        return BusinessRuleError(reason + " Contact an administrator for assistance.", status.HTTP_423_LOCKED)
    if booking.status == BookingStatus.COMPLETED.value:
        return BusinessRuleError(COMPLETED_READ_ONLY_MESSAGE)
    if booking.is_emergency:
        return BusinessRuleError(
            "Emergency change records can only be modified by an administrator.",
            status.HTTP_403_FORBIDDEN,
        )
    return None


def assert_booking_mutable(
    db: Session, booking: DeploymentBooking, actor: "Actor", app_settings: AppSettings | None = None
) -> None:
    error = schedule_restriction(db, booking, actor, app_settings)
    if error is not None:
        raise error


def is_followup_date(day: date, *, today: date | None = None) -> bool:
    """Today and the previous seven calendar days support append-only uploads."""
    today = today or today_local()
    return today - timedelta(days=FOLLOWUP_DAYS) <= day <= today


def assert_unlockable_date(day: date) -> None:
    if day < today_local() - timedelta(days=FOLLOWUP_DAYS):
        raise BusinessRuleError(
            "Dates older than seven days are read-only for document uploads and cannot be unlocked.",
            status.HTTP_423_LOCKED,
        )


def attachment_upload_restriction(
    db: Session, booking: DeploymentBooking, actor: "Actor", app_settings: AppSettings | None = None
) -> BusinessRuleError | None:
    """Recent unlocks permit new evidence, without granting scheduling or deletion rights."""
    if booking.deployment_date > today_local():
        return schedule_restriction(db, booking, actor, app_settings)
    if not is_followup_date(booking.deployment_date):
        return BusinessRuleError("Additional documents can only be uploaded for today and the previous seven days.", status.HTTP_423_LOCKED)
    if booking.status == BookingStatus.CANCELLED.value:
        return BusinessRuleError(CANCELLED_READ_ONLY_MESSAGE)
    if not actor.is_admin and booking.is_emergency:
        return BusinessRuleError("Emergency documents can only be uploaded by an administrator.", status.HTTP_403_FORBIDDEN)
    if not actor.is_admin and booking.status == BookingStatus.COMPLETED.value:
        return BusinessRuleError(COMPLETED_READ_ONLY_MESSAGE)
    slot = None if booking.is_emergency else booking.slot_number
    if not has_unlock_override(db, booking.deployment_date, slot):
        return BusinessRuleError("The Owner or a Release Manager must unlock additional uploads for this date or slot first.", status.HTTP_423_LOCKED)
    if not actor.is_admin and is_slot_manually_frozen(db, booking.deployment_date, slot):
        return BusinessRuleError(MANUAL_FREEZE_MESSAGE, status.HTTP_423_LOCKED)
    return None


def can_close_booking(booking: DeploymentBooking, *, is_admin: bool) -> bool:
    """Administrators can close open/in-progress records independently of date locks."""
    return is_admin and booking.status in {BookingStatus.BOOKED.value, BookingStatus.IN_PROGRESS.value}


def can_reopen_booking(booking: DeploymentBooking, *, is_admin: bool) -> bool:
    """Reopening changes lifecycle state only, independently of scheduling locks."""
    return is_admin and booking.status == BookingStatus.COMPLETED.value


def reopen_booking(db: Session, booking: DeploymentBooking, actor: "Actor") -> DeploymentBooking:
    """Restore the state before the latest closure, preserving work and evidence."""
    if not actor.is_admin:
        raise BusinessRuleError("Only the Owner or a Release Manager can reopen a schedule.", status.HTTP_403_FORBIDDEN)
    # Serialize repeated requests so a second click cannot reopen an already-open
    # record or append a duplicate reopen event in PostgreSQL.
    db.refresh(booking, attribute_names=["status"], with_for_update=True)
    if not can_reopen_booking(booking, is_admin=True):
        raise BusinessRuleError("Only completed/closed schedules can be reopened.")
    closure = db.scalar(
        select(BookingAudit)
        .where(BookingAudit.booking_id == booking.id, BookingAudit.event_type == "BOOKING_STATUS_CHANGED")
        .order_by(BookingAudit.id.desc())
        .limit(1)
    )
    restored = None
    if closure is not None:
        try:
            old_values = json.loads(closure.old_values or "{}")
            new_values = json.loads(closure.new_values or "{}")
        except (TypeError, ValueError):
            old_values = new_values = {}
        if isinstance(old_values, dict) and isinstance(new_values, dict) and new_values.get("status") == BookingStatus.COMPLETED.value:
            previous = old_values.get("status")
            if isinstance(previous, str) and previous in {BookingStatus.BOOKED.value, BookingStatus.IN_PROGRESS.value}:
                restored = previous
    # Older/imported records may lack a closure audit. Existing work details are
    # retained and indicate In Progress; otherwise restore Open (BOOKED).
    if restored is None:
        restored = BookingStatus.IN_PROGRESS.value if booking.work_started_at is not None or (booking.change_number or "").strip() else BookingStatus.BOOKED.value
    booking.status = restored
    audit_service.record(
        db,
        event_type="BOOKING_REOPENED",
        booking=booking,
        actor_type="ADMIN",
        admin_username=actor.admin_username,
        old_values={"status": BookingStatus.COMPLETED.value},
        new_values={"status": restored},
    )
    db.commit()
    return booking


def admin_freeze_override_reason(db: Session, booking: DeploymentBooking, actor: "Actor", supplied: str | None) -> str | None:
    """Administrators acting on a manually frozen slot leave an audited reason."""
    if actor.is_admin and is_slot_manually_frozen(db, booking.deployment_date, booking.slot_number):
        return (supplied or "").strip() or "Administrator override: manually frozen deployment slot."
    return None


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


def document_readiness(booking: DeploymentBooking, doc_types: list[DocumentType]) -> DocumentReadiness:
    """Readiness against the active configured document types, in display order."""
    counts: dict[str, int] = {}
    for att in booking.attachments:
        counts[att.category] = counts.get(att.category, 0) + 1

    items: list[DocumentStatus] = []
    for doc_type in doc_types:
        if not doc_type.is_active:
            continue
        count = counts.get(doc_type.key, 0)
        items.append(
            DocumentStatus(
                category=doc_type.key,
                label=doc_type.label,
                required=doc_type.is_required,
                multiple=doc_type.allow_multiple,
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
    readiness = document_readiness(booking, document_type_service.active_types(db))
    if not readiness.complete:
        raise BusinessRuleError(
            "Required deployment document missing: " + ", ".join(readiness.missing_labels)
        )


# --------------------------------------------------------------------------- #
# Schedule access
# --------------------------------------------------------------------------- #

#: Why a non-admin caller may act on a schedule (recorded on audit events).
ACCESS_SCHEDULER = "SCHEDULER"
ACCESS_TENANT_MEMBER = "TENANT_MEMBER"
ACCESS_COLLABORATOR = "COLLABORATOR"


@dataclass(frozen=True)
class Actor:
    """Who is making the change."""

    is_admin: bool
    admin_username: str | None = None
    requester_email: str | None = None
    user_id: int | None = None
    #: For non-admins: ACCESS_SCHEDULER, ACCESS_TENANT_MEMBER or ACCESS_COLLABORATOR.
    access: str | None = None

    @property
    def actor_type(self) -> str:
        return "ADMIN" if self.is_admin else "USER"


def audit(
    db: Session,
    actor: Actor,
    event_type: str,
    booking: DeploymentBooking | None,
    **values,
) -> BookingAudit:
    """Record an event attributed to the person who actually performed it."""
    return audit_service.record(
        db,
        event_type=event_type,
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=actor.requester_email or (booking.requester_email if booking is not None else None),
        admin_username=actor.admin_username,
        actor_access=actor.access,
        **values,
    )


def assert_tenant_access(db: Session, actor: Actor, tenant_id: int) -> None:
    """Enforce tenant scope for writers.

    Member Pool is the self-service/unassigned scheduling pool. Those users may
    choose any active tenant from the tenant master. Once a user is assigned to
    one or more tenant subgroups, scheduling is restricted to those groups.
    """
    if actor.is_admin:
        return
    if actor.user_id is None:
        raise BusinessRuleError("Authentication required.", status.HTTP_401_UNAUTHORIZED)
    if group_service.is_management(db, actor.user_id):
        raise BusinessRuleError("Management access is read-only.", status.HTTP_403_FORBIDDEN)
    allowed = group_service.tenant_ids_for_user(db, actor.user_id)
    if tenant_id in allowed:
        return
    if not allowed and group_service.is_member_pool(db, actor.user_id):
        return
    if tenant_id not in allowed:
        raise BusinessRuleError(
            "You can schedule only for tenant groups you belong to.",
            status.HTTP_403_FORBIDDEN,
        )


def user_is_collaborator(db: Session, booking: DeploymentBooking, user_id: int) -> bool:
    return db.scalar(
        select(BookingCollaborator.id).where(
            BookingCollaborator.booking_id == booking.id,
            BookingCollaborator.user_id == user_id,
        )
    ) is not None


def schedule_access_basis(db: Session, booking: DeploymentBooking, user_id: int | None) -> str | None:
    """Relationship that lets a non-admin work on this schedule, or None.

    The original scheduler, any active member of the schedule's tenant group
    and any explicitly added collaborator share the same schedule-level
    permissions. Management is always read-only, whatever else it belongs to.
    """
    if user_id is None or group_service.is_management(db, user_id):
        return None
    if booking.created_by_user_id == user_id:
        return ACCESS_SCHEDULER
    if booking.tenant_id in group_service.tenant_ids_for_user(db, user_id):
        return ACCESS_TENANT_MEMBER
    if user_is_collaborator(db, booking, user_id):
        return ACCESS_COLLABORATOR
    return None


def schedule_actor(db: Session, booking: DeploymentBooking, *, admin=None, user=None) -> Actor:
    """The single authorization gate for modifying a schedule.

    ``admin`` is set only for a non-Management Owner/Release Manager (see
    ``optional_admin``). Everyone else needs a schedule relationship. The
    record-state rules (lock, freeze, dates, status) are applied afterwards by
    ``schedule_restriction``.
    """
    principal = admin or user
    if principal is None:
        raise BusinessRuleError("Authentication required.", status.HTTP_401_UNAUTHORIZED)
    if group_service.is_management(db, principal.user_id):
        raise BusinessRuleError("Management access is read-only.", status.HTTP_403_FORBIDDEN)
    if admin is not None:
        return Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    access = schedule_access_basis(db, booking, user.user_id)
    if access is None:
        raise BusinessRuleError(
            "You are not authorized to modify this schedule. Only its tenant group, "
            "its scheduler, its collaborators and Release Managers can change it.",
            status.HTTP_403_FORBIDDEN,
        )
    return Actor(is_admin=False, requester_email=user.email, user_id=user.user_id, access=access)


def collaborator_change_restriction(
    db: Session, booking: DeploymentBooking, *, user_id: int | None, is_admin: bool
) -> BusinessRuleError | None:
    """Who may add/remove collaborators on this schedule, and when.

    Only the original scheduler (or an Admin/RM) delegates access, never
    Management. Delegation is pointless where collaborators could never act:
    cancelled, past/current and emergency records; completed records are
    read-only for everyone but Admin/RM.
    """
    if user_id is None:
        return BusinessRuleError("Authentication required.", status.HTTP_401_UNAUTHORIZED)
    if group_service.is_management(db, user_id):
        return BusinessRuleError("Management access is read-only.", status.HTTP_403_FORBIDDEN)
    if not is_admin and booking.created_by_user_id != user_id:
        return BusinessRuleError("Only the original scheduler can manage collaborators.", status.HTTP_403_FORBIDDEN)
    if booking.status == BookingStatus.CANCELLED.value:
        return BusinessRuleError(CANCELLED_READ_ONLY_MESSAGE)
    if booking.deployment_date <= today_local():
        return BusinessRuleError(PAST_CURRENT_READ_ONLY_MESSAGE, status.HTTP_423_LOCKED)
    if booking.is_emergency:
        return BusinessRuleError("Emergency changes are handled by Admin/RM only and take no collaborators.")
    if not is_admin and booking.status == BookingStatus.COMPLETED.value:
        return BusinessRuleError(COMPLETED_READ_ONLY_MESSAGE)
    return None


@dataclass(frozen=True)
class SchedulePermissions:
    can_edit: bool
    can_cancel: bool
    can_reschedule: bool
    can_manage_attachments: bool
    can_manage_collaborators: bool
    access: str | None


def schedule_permissions(
    db: Session,
    booking: DeploymentBooking,
    *,
    user_id: int | None,
    is_admin: bool,
    app_settings: AppSettings | None = None,
) -> SchedulePermissions:
    """What the UI may offer; mirrors exactly what the write endpoints enforce."""
    none = SchedulePermissions(False, False, False, False, False, None)
    if user_id is None or group_service.is_management(db, user_id):
        return none
    if is_admin:
        actor = Actor(is_admin=True, user_id=user_id)
    else:
        access = schedule_access_basis(db, booking, user_id)
        if access is None:
            return none
        actor = Actor(is_admin=False, user_id=user_id, access=access)
    editable = schedule_restriction(db, booking, actor, app_settings) is None
    movable = editable and booking.status != BookingStatus.COMPLETED.value
    return SchedulePermissions(
        can_edit=editable,
        can_cancel=movable,
        can_reschedule=movable,
        can_manage_attachments=editable,
        can_manage_collaborators=collaborator_change_restriction(
            db, booking, user_id=user_id, is_admin=is_admin
        ) is None,
        access=actor.access,
    )


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


def normal_slot_rejection(
    day: date,
    slot: schedule_service.ResolvedSlot | None,
    *,
    today: date,
    frozen_dates: set[date],
    manually_frozen: bool,
    occupied: bool = False,
    lock_overridden: bool = False,
) -> tuple[str, int] | None:
    """Shared normal availability policy for board, picker and API writes.

    Caller privileges intentionally have no place in this policy. An Admin/RM
    unlock (``lock_overridden``) lifts only the automatic upcoming-date lock.
    """
    if day <= today:
        return PAST_CURRENT_READ_ONLY_MESSAGE, status.HTTP_423_LOCKED
    if day in frozen_dates and not lock_overridden:
        return AUTOMATIC_FREEZE_MESSAGE, status.HTTP_423_LOCKED
    if not is_deployment_weekday(day):
        return "Deployments can only be scheduled Sunday to Thursday.", status.HTTP_400_BAD_REQUEST
    if slot is None:
        return "The selected deployment slot does not exist.", status.HTTP_404_NOT_FOUND
    if not slot.bookable:
        return slot.unavailable_reason or "That deployment slot is disabled for this date.", status.HTTP_400_BAD_REQUEST
    if manually_frozen:
        return MANUAL_FREEZE_MESSAGE, status.HTTP_423_LOCKED
    if occupied:
        return SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT
    return None


def _validate_slot_target(
    db: Session,
    day: date,
    slot_number: int | None,
    actor: Actor,
    app_settings: AppSettings,
    *,
    manual_override: bool = False,
    override_reason: str | None = None,
    exclude_id: int | None = None,
) -> schedule_service.ResolvedSlot:
    plan = schedule_service.resolve_day(db, day, app_settings=app_settings)
    slot = next((s for s in plan.slots if s.slot_number == slot_number), None)
    frozen_dates = automatic_frozen_dates(db, app_settings)
    lock_overridden = has_unlock_override(db, day, slot_number)
    occupied = _slot_taken(db, day, slot_number, exclude_id=exclude_id)
    if manual_override:
        # Explicit exceptional workflow only; never used by normal availability.
        if not actor.is_admin or not (override_reason or "").strip():
            raise BusinessRuleError("Manual scheduling override requires an administrator and a reason.", status.HTTP_403_FORBIDDEN)
        assert_day_not_past(day)
        if day in frozen_dates and not lock_overridden:
            raise BusinessRuleError(AUTOMATIC_FREEZE_MESSAGE, status.HTTP_423_LOCKED)
        if slot is None:
            raise BusinessRuleError("The selected deployment slot does not exist.", status.HTTP_404_NOT_FOUND)
        if occupied:
            raise BusinessRuleError(SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT)
    else:
        rejection = normal_slot_rejection(
            day, slot, today=today_local(), frozen_dates=frozen_dates,
            manually_frozen=is_slot_manually_frozen(db, day, slot_number), occupied=occupied,
            lock_overridden=lock_overridden,
        )
        if rejection:
            raise BusinessRuleError(*rejection)
    assert slot is not None
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
    weekly_limit: int,
    exclude_id: int | None = None,
) -> bool:
    """Returns True when an admin override was actually applied."""
    if is_emergency:
        # Emergency bookings never count against the normal weekly limit.
        return False
    count = weekly_normal_count(db, tenant_id, day, exclude_id=exclude_id)
    if count < weekly_limit:
        return False
    # Administrators automatically bypass tenant weekly limits. The boolean
    # return is retained so the audit trail can record that a bypass happened;
    # no checkbox or manually-entered reason is required.
    if actor.is_admin:
        return True
    raise BusinessRuleError(
        f"Weekly booking limit reached. {tenant_name} already has "
        f"{count} deployment slot{'s' if count != 1 else ''} booked for this week "
        f"(limit: {weekly_limit}).",
        status.HTTP_409_CONFLICT,
    )


def _normalise_jira_number(
    payload: BookingCreate | BookingUpdate, app_settings: AppSettings
) -> str | None:
    jira_number = (payload.jira_number or "").strip() or None
    if app_settings.jira_required_at_booking and jira_number is None:
        raise BusinessRuleError(
            "Jira No. is required by the current booking rules.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return jira_number


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
    assert_tenant_access(db, actor, tenant.id)
    jira_number = _normalise_jira_number(payload, app_settings)
    assert_day_not_past(payload.deployment_date)
    target_slot = None if payload.is_emergency else payload.slot_number
    if is_schedule_locked(db, payload.deployment_date, target_slot, app_settings):
        raise BusinessRuleError(AUTOMATIC_FREEZE_MESSAGE, status.HTTP_423_LOCKED)
    if payload.is_emergency:
        if not actor.is_admin:
            raise BusinessRuleError("Only administrators can create emergency changes.", status.HTTP_403_FORBIDDEN)
        # Emergency changes are an explicit Admin queue; date protections still apply.
        is_emergency = True
    else:
        _validate_slot_target(db, payload.deployment_date, payload.slot_number, actor, app_settings, manual_override=payload.manual_override, override_reason=payload.override_reason)
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
        weekly_limit=(
            tenant.weekly_booking_limit
            if tenant.weekly_booking_limit is not None
            else app_settings.weekly_booking_limit
        ),
    )
    override_reason = (payload.override_reason or "").strip() if payload.manual_override else None
    if override_applied:
        override_reason = (payload.override_reason or "").strip() or (
            "Administrator automatic override: tenant weekly booking limit."
        )

    requester = db.get(User, actor.user_id) if actor.user_id is not None else None
    requester_name = requester.full_name if requester is not None else (actor.admin_username or "System")
    requester_email = requester.email if requester is not None else (actor.requester_email or "")

    booking = DeploymentBooking(
        booking_reference=next_booking_reference(db, payload.deployment_date),
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        created_by_user_id=actor.user_id,
        deployment_date=payload.deployment_date,
        slot_number=None if is_emergency else payload.slot_number,
        jira_number=jira_number,
        jira_url=payload.jira_url,
        environment="PROD",
        technology=payload.technology.value,
        requester_name=requester_name,
        requester_email=requester_email,
        requester_phone=None,
        verifier_name=payload.verifier_name,
        verifier_email=str(payload.verifier_email) if payload.verifier_email else "",
        git_repository=payload.git_repository,
        implementation_summary=payload.implementation_summary or "",
        deployment_description=payload.deployment_description or "",
        additional_comments=payload.additional_comments or None,
        justification=payload.justification,
        impacted_region=payload.impacted_region,
        status=BookingStatus.BOOKED.value,
        is_emergency=is_emergency,
        emergency_reason=payload.emergency_reason or None,
        emergency_approval_reference=payload.emergency_approval_reference or None,
        emergency_approver=payload.emergency_approver or None,
        business_justification=payload.business_justification or None,
    )
    db.add(booking)
    _flush_new_booking(db, booking)

    audit(
        db,
        actor,
        "EMERGENCY_BOOKING_CREATED" if is_emergency else "BOOKING_CREATED",
        booking,
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
    assert_booking_mutable(db, booking, actor, app_settings)

    override_reason: str | None = (payload.override_reason or "").strip() if payload.manual_override else None
    override_reason = admin_freeze_override_reason(db, booking, actor, payload.override_reason) or override_reason

    before = audit_service.snapshot(booking)

    new_day = payload.deployment_date or booking.deployment_date
    new_slot_number = payload.slot_number or booking.slot_number
    assert_day_not_past(new_day)
    if is_schedule_locked(db, new_day, None if booking.is_emergency else new_slot_number, app_settings):
        raise BusinessRuleError(AUTOMATIC_FREEZE_MESSAGE, status.HTTP_423_LOCKED)
    moved = (new_day, new_slot_number) != (booking.deployment_date, booking.slot_number)
    if moved and booking.status == BookingStatus.COMPLETED.value:
        raise BusinessRuleError("A completed/closed booking cannot be rescheduled.")
    if moved and not booking.is_emergency:
        _validate_slot_target(db, new_day, new_slot_number, actor, app_settings, exclude_id=booking.id, manual_override=payload.manual_override, override_reason=payload.override_reason)

    tenant = resolve_tenant(db, payload.tenant_id)
    if tenant.id != booking.tenant_id:
        # Access to this schedule was already established; moving it to a
        # different tenant additionally needs scheduling rights for that tenant.
        assert_tenant_access(db, actor, tenant.id)
    jira_number = _normalise_jira_number(payload, app_settings)
    if not booking.is_emergency and (moved or tenant.id != booking.tenant_id):
        applied = _validate_weekly_limit(
            db,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            day=new_day,
            is_emergency=False,
            actor=actor,
            app_settings=app_settings,
            weekly_limit=(
                tenant.weekly_booking_limit
                if tenant.weekly_booking_limit is not None
                else app_settings.weekly_booking_limit
            ),
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
    booking.jira_number = jira_number
    booking.jira_url = payload.jira_url
    booking.technology = payload.technology.value
    booking.verifier_name = payload.verifier_name
    booking.verifier_email = str(payload.verifier_email) if payload.verifier_email else ""
    booking.git_repository = payload.git_repository
    booking.implementation_summary = payload.implementation_summary or ""
    booking.deployment_description = payload.deployment_description or ""
    booking.additional_comments = payload.additional_comments or None
    booking.justification = payload.justification
    booking.impacted_region = payload.impacted_region
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
        audit(
            db,
            actor,
            "SLOT_CHANGED" if moved else "BOOKING_EDITED",
            booking,
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
    if booking.status == BookingStatus.CANCELLED.value:
        assert_booking_not_past(booking)
        raise BusinessRuleError("This booking is already cancelled.")
    assert_booking_mutable(db, booking, actor, app_settings)
    if booking.status == BookingStatus.COMPLETED.value:
        raise BusinessRuleError("A completed/closed booking cannot be cancelled.")
    reason = admin_freeze_override_reason(db, booking, actor, override_reason)

    before = audit_service.snapshot(booking)
    booking.status = BookingStatus.CANCELLED.value
    booking.cancelled_at = now_utc()
    booking.cancelled_by_user_id = actor.user_id
    db.flush()
    # The slot itself is never deleted: releasing the booking is what frees it,
    # and the record survives so the cancellation stays auditable.
    audit(
        db,
        actor,
        "BOOKING_CANCELLED",
        booking,
        override_reason=reason or None,
        old_values={
            "status": before["status"],
            "deployment_date": before["deployment_date"],
            "slot_number": before["slot_number"],
            "tenant_id": before["tenant_id"],
            "tenant_name": before["tenant_name"],
            "jira_number": before["jira_number"],
        },
        new_values={
            "status": booking.status,
            "cancelled_at": booking.cancelled_at,
            "cancelled_by_user_id": booking.cancelled_by_user_id,
        },
    )
    db.commit()
    return booking


# --------------------------------------------------------------------------- #
# Reschedule
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SlotOption:
    """One destination the current caller is genuinely allowed to move to."""

    deployment_date: date
    slot_number: int
    slot_name: str
    start_time: time
    end_time: time


def _effective_weekly_limit(tenant: Tenant, app_settings: AppSettings) -> int:
    return (
        tenant.weekly_booking_limit
        if tenant.weekly_booking_limit is not None
        else app_settings.weekly_booking_limit
    )


#: How far ahead the reschedule search looks for free slots.
RESCHEDULE_SEARCH_DAYS = 60


def next_available_slots(
    db: Session, booking: DeploymentBooking, actor: Actor, *, limit: int = 12
) -> list[SlotOption]:
    """Destinations this caller may actually book, earliest date first.

    Every rule that ``_validate_slot_target`` enforces on submit is applied
    here too, so the picker never offers a slot that would then be rejected.
    Normal users additionally have the tenant weekly limit applied per week.
    """
    app_settings = get_app_settings(db)
    if booking.is_emergency or booking.status in {BookingStatus.CANCELLED.value, BookingStatus.COMPLETED.value}:
        return []
    if schedule_restriction(db, booking, actor, app_settings) is not None:
        return []

    tenant = db.get(Tenant, booking.tenant_id)
    if tenant is None or not tenant.is_active:
        return []
    weekly_limit = _effective_weekly_limit(tenant, app_settings)
    frozen_dates = automatic_frozen_dates(db, app_settings)
    configs = schedule_service.slot_configurations(db)

    start = today_local() + timedelta(days=1)
    end = start + timedelta(days=RESCHEDULE_SEARCH_DAYS)
    holidays = schedule_service.holidays_between(db, start, end)
    capacities = schedule_service.capacities_between(db, start, end)
    manual_freezes = slot_freezes_between(db, start, end)
    overrides = lock_overrides_between(db, start, end)

    taken: dict[date, set[int]] = {}
    for other in schedule_service.active_bookings_between(db, start, end):
        if other.slot_number is not None and other.id != booking.id:
            taken.setdefault(other.deployment_date, set()).add(other.slot_number)

    week_has_room: dict[date, bool] = {}
    options: list[SlotOption] = []
    cursor = start
    while cursor <= end and len(options) < limit:
        day = cursor
        cursor += timedelta(days=1)

        if not is_deployment_weekday(day):
            continue

        if not actor.is_admin:
            sunday = week_start(day)
            if sunday not in week_has_room:
                used = weekly_normal_count(db, booking.tenant_id, day, exclude_id=booking.id)
                week_has_room[sunday] = used < weekly_limit
            if not week_has_room[sunday]:
                continue

        plan = schedule_service.resolve_day(
            db,
            day,
            app_settings=app_settings,
            configs=configs,
            holiday=holidays.get(day),
            capacity=capacities.get(day),
            prefetched=True,
        )
        for slot in plan.slots:
            if len(options) >= limit:
                break
            if (day, slot.slot_number) == (booking.deployment_date, booking.slot_number):
                continue
            if normal_slot_rejection(
                day, slot, today=today_local(), frozen_dates=frozen_dates,
                manually_frozen=(day, slot.slot_number) in manual_freezes,
                occupied=slot.slot_number in taken.get(day, set()),
                lock_overridden=override_applies(overrides, day, slot.slot_number),
            ):
                continue
            options.append(
                SlotOption(
                    deployment_date=day,
                    slot_number=slot.slot_number,
                    slot_name=slot.name,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                )
            )
    return options


def reschedule_booking(
    db: Session,
    booking: DeploymentBooking,
    new_day: date,
    new_slot_number: int,
    actor: Actor,
    override_reason: str | None = None,
) -> DeploymentBooking:
    """Move a booking to another date/slot as a single transaction.

    The record keeps its identity, reference, attachments, RM assignment and
    every other field: only ``deployment_date`` and ``slot_number`` change. The
    destination is validated first and the partial unique index makes the final
    write the arbiter, so a slot lost to a concurrent booking leaves the
    original untouched.
    """
    app_settings = get_app_settings(db)
    assert_booking_not_past(booking)
    if booking.status in {BookingStatus.CANCELLED.value, BookingStatus.COMPLETED.value}:
        raise BusinessRuleError("A cancelled or completed/closed booking cannot be rescheduled.")
    if booking.is_emergency:
        raise BusinessRuleError(
            "Emergency changes have no deployment slot and are moved by date from the "
            "administrator tools.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    assert_booking_mutable(db, booking, actor, app_settings)
    reason = admin_freeze_override_reason(db, booking, actor, override_reason)

    if (new_day, new_slot_number) == (booking.deployment_date, booking.slot_number):
        raise BusinessRuleError("This booking is already scheduled in that slot.")

    # Re-validate the destination at submit time: the picker's view of
    # availability may be seconds out of date.
    _validate_slot_target(db, new_day, new_slot_number, actor, app_settings, exclude_id=booking.id)
    if _slot_taken(db, new_day, new_slot_number, exclude_id=booking.id):
        raise BusinessRuleError(SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT)

    tenant = resolve_tenant(db, booking.tenant_id)
    limit_overridden = _validate_weekly_limit(
        db,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        day=new_day,
        is_emergency=False,
        actor=actor,
        app_settings=app_settings,
        weekly_limit=_effective_weekly_limit(tenant, app_settings),
        exclude_id=booking.id,
    )
    if limit_overridden:
        reason = reason or (override_reason or "").strip() or (
            "Administrator automatic override: tenant weekly booking limit."
        )

    previous = {
        "deployment_date": booking.deployment_date,
        "slot_number": booking.slot_number,
        "tenant_id": booking.tenant_id,
        "tenant_name": booking.tenant_name,
        "jira_number": booking.jira_number,
    }
    booking.deployment_date = new_day
    booking.slot_number = new_slot_number
    try:
        db.flush()
    except IntegrityError:
        # Somebody won the destination between validation and write. Rolling
        # back restores the original date/slot; nothing about the booking is
        # lost and no partial move is ever visible.
        db.rollback()
        raise BusinessRuleError(SLOT_TAKEN_MESSAGE, status.HTTP_409_CONFLICT) from None

    audit(
        db,
        actor,
        "BOOKING_RESCHEDULED",
        booking,
        override_reason=reason or None,
        old_values=previous,
        new_values={
            "deployment_date": booking.deployment_date,
            "slot_number": booking.slot_number,
            "tenant_id": booking.tenant_id,
            "tenant_name": booking.tenant_name,
            "jira_number": booking.jira_number,
        },
    )
    db.commit()
    db.refresh(booking)
    return booking


def delete_booking(db: Session, booking: DeploymentBooking, actor: Actor) -> None:
    """Hard delete a non-historical booking while retaining its audit trail."""
    assert_booking_not_past(booking)
    if is_schedule_locked(db, booking.deployment_date, None if booking.is_emergency else booking.slot_number):
        raise BusinessRuleError(AUTOMATIC_FREEZE_MESSAGE, status.HTTP_423_LOCKED)
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
        # The booking row is about to go, so carry its tenant explicitly.
        tenant_id=booking.tenant_id,
    )
    deleted_event.booking_reference = reference
    db.delete(booking)
    db.commit()


def assign_users_to_booking(
    db: Session, booking: DeploymentBooking, user_ids: list[int], actor: Actor
) -> DeploymentBooking:
    """Replace a booking's assignee with exactly one Release Manager.

    The protected Owner account may assign work but can never be an assignee.
    Release Manager group membership is the source of truth; a Release Manager
    may assign the booking to themselves or to another Release Manager.
    """
    if not actor.is_admin:
        raise BusinessRuleError(
            "Only the Owner or a Release Manager can assign Release Managers.",
            status.HTTP_403_FORBIDDEN,
        )
    assert_booking_mutable(db, booking, actor)
    if booking.status in {BookingStatus.CANCELLED.value, BookingStatus.COMPLETED.value}:
        raise BusinessRuleError("A cancelled or completed booking cannot be assigned.")

    unique_ids = list(dict.fromkeys(user_ids))
    if len(unique_ids) != 1:
        raise BusinessRuleError(
            "Select exactly one Release Manager for this schedule.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    users = list(
        db.scalars(
            select(User)
            .join(GroupMembership, GroupMembership.user_id == User.id)
            .join(AccessGroup, AccessGroup.id == GroupMembership.group_id)
            .where(
                User.id.in_(unique_ids),
                User.is_active.is_(True),
                User.is_owner.is_(False),
                AccessGroup.group_type == GroupType.RELEASE_MANAGERS.value,
                AccessGroup.is_active.is_(True),
            )
            .distinct()
        ).all()
    )
    found = {u.id for u in users}
    missing = [uid for uid in unique_ids if uid not in found]
    if missing:
        raise BusinessRuleError(
            "One or more selected Release Managers are inactive, invalid, or not assignable. "
            "The protected Owner account cannot be assigned.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Serialize replacements on PostgreSQL so simultaneous selections cannot
    # each append an assignee after reading the same old assignment list.
    db.execute(select(DeploymentBooking).where(DeploymentBooking.id == booking.id).with_for_update())
    db.expire(booking, ["assignments"])
    before_ids = [a.user_id for a in booking.assignments]
    before_names = [a.user.full_name for a in booking.assignments if a.user is not None]
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
        old_values={"assigned_user_ids": before_ids, "assigned_user_names": before_names},
        new_values={
            "assigned_user_ids": unique_ids,
            "assigned_user_names": [next(u.full_name for u in users if u.id == uid) for uid in unique_ids],
        },
    )
    db.commit()
    db.refresh(booking)
    return booking


def user_is_assigned(booking: DeploymentBooking, user_id: int) -> bool:
    return any(a.user_id == user_id for a in booking.assignments)


def start_work(
    db: Session, booking: DeploymentBooking, change_number: str, actor: Actor
) -> DeploymentBooking:
    """An assigned Release Manager supplies the separate Change No. and starts work."""
    assert_booking_mutable(db, booking, actor)
    if booking.status not in {BookingStatus.BOOKED.value, BookingStatus.IN_PROGRESS.value}:
        raise BusinessRuleError("Only booked or in-progress tasks can be started or updated.")
    if not change_number.strip():
        raise BusinessRuleError("Change No. is required to start work.")

    account = db.get(User, actor.user_id) if actor.user_id is not None else None
    is_release_manager = (
        account is not None
        and account.is_active
        and not account.is_owner
        and group_service.is_release_manager(db, account.id)
    )
    if (
        not is_release_manager
        or actor.user_id is None
        or not user_is_assigned(booking, actor.user_id)
    ):
        raise BusinessRuleError(
            "Only an assigned Release Manager can start work on this booking.",
            status.HTTP_403_FORBIDDEN,
        )
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
