"""Booking business rules.

This module is the single source of truth for:
  * slot existence / enablement / holiday blocking
  * emergency-slot access (admin only)
  * the per-tenant weekly limit (and admin override)
  * the configurable edit/cancel freeze window
  * booking ownership (email + PIN, or the manage token)
  * document readiness

The API layer never re-implements any of these; it only calls in here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_STATUSES,
    DOCUMENT_LABELS,
    MULTI_FILE_CATEGORIES,
    BookingAttachment,
    BookingStatus,
    DeploymentBooking,
    DocumentCategory,
    Tenant,
)
from ..schemas.booking import BookingCreate, BookingUpdate, DocumentReadiness, DocumentStatus
from ..security import generate_manage_token, hash_manage_token, hash_secret, verify_secret
from ..utils.dates import format_day, format_time, now_utc, slot_start_utc, today_local, week_start
from . import audit_service, schedule_service
from .settings_service import AppSettings, get_app_settings

_WS = re.compile(r"\s+")


class BusinessRuleError(HTTPException):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=message)


def tenant_key(name: str) -> str:
    """Weekly limits are per tenant, matched case- and spacing-insensitively."""
    return _WS.sub(" ", (name or "").strip()).lower()


def resolve_tenant(db: Session, tenant_id: int | None, tenant_name: str | None) -> Tenant:
    tenant = db.get(Tenant, tenant_id) if tenant_id is not None else None
    if tenant_id is None and tenant_name:
        tenant = db.scalars(
            select(Tenant).where(func.lower(Tenant.name) == tenant_name.strip().lower())
        ).first()
        if tenant is None and tenant_id is None:
            legacy_name = tenant_name.strip()
            tenant = Tenant(
                name=legacy_name,
                tenant_code=f"LEGACY-{tenant_key(legacy_name)[:50]}",
                is_active=True,
            )
            db.add(tenant)
            db.flush()
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
# Freeze window
# --------------------------------------------------------------------------- #


def lock_deadline(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> datetime | None:
    app_settings = app_settings or get_app_settings(db)
    slot = schedule_service.find_slot(db, booking.deployment_date, booking.slot_number)
    if slot is None:
        return None
    start = slot_start_utc(booking.deployment_date, slot.start_time)
    return start - timedelta(hours=app_settings.booking_freeze_hours)


def is_locked_for_public(db: Session, booking: DeploymentBooking, app_settings: AppSettings | None = None) -> bool:
    if booking.status == BookingStatus.CANCELLED.value:
        return True
    deadline = lock_deadline(db, booking, app_settings)
    if deadline is None:
        return True
    return now_utc() >= deadline


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


def verify_owner(booking: DeploymentBooking, email: str, pin: str) -> bool:
    if (booking.requester_email or "").strip().lower() != (email or "").strip().lower():
        return False
    return verify_secret(pin, booking.booking_pin_hash)


def booking_for_manage_token(db: Session, token: str) -> DeploymentBooking | None:
    if not token:
        return None
    return db.scalars(
        select(DeploymentBooking).where(DeploymentBooking.manage_token_hash == hash_manage_token(token))
    ).first()


@dataclass(frozen=True)
class Actor:
    """Who is making the change."""

    is_admin: bool
    admin_username: str | None = None
    requester_email: str | None = None
    user_id: int | None = None

    @property
    def actor_type(self) -> str:
        return "ADMIN" if self.is_admin else "PUBLIC"


# --------------------------------------------------------------------------- #
# Slot / limit validation
# --------------------------------------------------------------------------- #


def weekly_normal_count(db: Session, tenant_id: int, any_day: date, *, exclude_id: int | None = None) -> int:
    monday = week_start(any_day)
    friday = monday + timedelta(days=4)
    stmt = select(func.count(DeploymentBooking.id)).where(
        DeploymentBooking.tenant_id == tenant_id,
        DeploymentBooking.deployment_date >= monday,
        DeploymentBooking.deployment_date <= friday,
        DeploymentBooking.is_emergency.is_(False),
        DeploymentBooking.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id is not None:
        stmt = stmt.where(DeploymentBooking.id != exclude_id)
    return int(db.scalar(stmt) or 0)


def _validate_slot_target(
    db: Session,
    day: date,
    slot_number: int,
    actor: Actor,
    app_settings: AppSettings,
) -> schedule_service.ResolvedSlot:
    if day < today_local():
        raise BusinessRuleError("Deployment date cannot be in the past.")
    if day.weekday() >= 5:
        raise BusinessRuleError("Deployments can only be scheduled Monday to Friday.")

    plan = schedule_service.resolve_day(db, day, app_settings=app_settings)
    slot = next((s for s in plan.slots if s.slot_number == slot_number), None)
    if slot is None:
        raise BusinessRuleError("The selected deployment slot does not exist.", status.HTTP_404_NOT_FOUND)
    if slot.is_emergency and not actor.is_admin:
        raise BusinessRuleError(
            "Slot 5 is reserved for emergency changes and can only be booked by an administrator.",
            status.HTTP_403_FORBIDDEN,
        )
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
    if actor.is_admin and override:
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


def _require_override_reason(app_settings: AppSettings, reason: str | None, what: str) -> str:
    reason = (reason or "").strip()
    if app_settings.require_admin_override_reason and not reason:
        raise BusinessRuleError(f"An override reason is required to {what}.")
    return reason


# --------------------------------------------------------------------------- #
# Create / update / cancel
# --------------------------------------------------------------------------- #


SLOT_TAKEN_MESSAGE = (
    "This slot has just been booked by another user. Please select another available slot."
)


def _slot_taken(db: Session, day: date, slot_number: int, exclude_id: int | None = None) -> bool:
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


def create_booking(db: Session, payload: BookingCreate, actor: Actor) -> tuple[DeploymentBooking, str]:
    app_settings = get_app_settings(db)
    tenant = resolve_tenant(db, payload.tenant_id, payload.tenant_name)
    slot = _validate_slot_target(db, payload.deployment_date, payload.slot_number, actor, app_settings)
    is_emergency = slot.is_emergency
    _validate_emergency_fields(payload, is_emergency)

    key = tenant_key(tenant.name)
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
        override_reason = _require_override_reason(
            app_settings, payload.override_reason, "exceed the weekly booking limit"
        )

    manage_token = generate_manage_token()
    booking = DeploymentBooking(
        booking_reference=next_booking_reference(db, payload.deployment_date),
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_key=key,
        created_by_user_id=actor.user_id,
        deployment_date=payload.deployment_date,
        slot_number=payload.slot_number,
        jira_change=payload.jira_change,
        jira_task=payload.jira_task or None,
        jira_url=payload.jira_url,
        environment=payload.environment or "PROD",
        technology=payload.technology.value,
        requester_name=payload.requester_name,
        requester_email=str(payload.requester_email),
        requester_phone=payload.requester_phone or None,
        booking_pin_hash=hash_secret(payload.booking_pin),
        manage_token_hash=hash_manage_token(manage_token),
        verifier_name=payload.verifier_name,
        verifier_email=str(payload.verifier_email),
        git_repository=payload.git_repository,
        implementation_summary=payload.implementation_summary,
        deployment_description=payload.deployment_description,
        additional_comments=payload.additional_comments or None,
        status=BookingStatus.BOOKED.value,
        is_emergency=is_emergency,
        emergency_reason=payload.emergency_reason or None,
        emergency_approval_reference=payload.emergency_approval_reference or None,
        emergency_approver=payload.emergency_approver or None,
        business_justification=payload.business_justification or None,
        created_by_admin=actor.admin_username if actor.is_admin else None,
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
    db.commit()
    return booking, manage_token


def update_booking(
    db: Session,
    booking: DeploymentBooking,
    payload: BookingUpdate,
    actor: Actor,
) -> DeploymentBooking:
    app_settings = get_app_settings(db)
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("This booking has been cancelled and can no longer be edited.")

    override_reason: str | None = None
    if not actor.is_admin:
        if is_locked_for_public(db, booking, app_settings):
            raise BusinessRuleError(
                f"Changes are disabled within {app_settings.booking_freeze_hours} hours of the "
                "deployment. Contact an administrator for assistance.",
                status.HTTP_423_LOCKED,
            )
        if booking.is_emergency:
            raise BusinessRuleError(
                "Emergency change records can only be modified by an administrator.",
                status.HTTP_403_FORBIDDEN,
            )
    elif is_locked_for_public(db, booking, app_settings):
        override_reason = _require_override_reason(
            app_settings, payload.override_reason, "edit a booking inside the freeze window"
        )

    before = audit_service.snapshot(booking)

    new_day = payload.deployment_date or booking.deployment_date
    new_slot_number = payload.slot_number or booking.slot_number
    moved = (new_day, new_slot_number) != (booking.deployment_date, booking.slot_number)
    if moved:
        slot = _validate_slot_target(db, new_day, new_slot_number, actor, app_settings)
        if slot.is_emergency != booking.is_emergency:
            raise BusinessRuleError(
                "A regular booking cannot be moved into the emergency slot (or vice versa). "
                "Cancel it and create the correct booking type instead."
            )

    tenant = resolve_tenant(db, payload.tenant_id, payload.tenant_name)
    new_key = tenant_key(tenant.name)
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
            override_reason = _require_override_reason(
                app_settings, payload.override_reason, "exceed the weekly booking limit"
            )

    _validate_emergency_fields(payload, booking.is_emergency)

    booking.tenant_id = tenant.id
    booking.tenant_name = tenant.name
    booking.tenant_key = new_key
    booking.deployment_date = new_day
    booking.slot_number = new_slot_number
    booking.jira_change = payload.jira_change
    booking.jira_task = payload.jira_task or None
    booking.jira_url = payload.jira_url
    booking.environment = payload.environment or "PROD"
    booking.technology = payload.technology.value
    booking.requester_name = payload.requester_name
    booking.requester_email = str(payload.requester_email)
    booking.requester_phone = payload.requester_phone or None
    booking.verifier_name = payload.verifier_name
    booking.verifier_email = str(payload.verifier_email)
    booking.git_repository = payload.git_repository
    booking.implementation_summary = payload.implementation_summary
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
    if booking.status == BookingStatus.CANCELLED.value:
        raise BusinessRuleError("This booking is already cancelled.")

    reason: str | None = None
    if not actor.is_admin:
        if is_locked_for_public(db, booking, app_settings):
            raise BusinessRuleError(
                f"Changes are disabled within {app_settings.booking_freeze_hours} hours of the "
                "deployment. Contact an administrator for assistance.",
                status.HTTP_423_LOCKED,
            )
        if booking.is_emergency:
            raise BusinessRuleError(
                "Emergency change records can only be cancelled by an administrator.",
                status.HTTP_403_FORBIDDEN,
            )
    elif is_locked_for_public(db, booking, app_settings):
        reason = _require_override_reason(
            app_settings, override_reason, "cancel a booking inside the freeze window"
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
    """Hard delete. Admin-only; attachment files are removed by the caller."""
    audit_service.record(
        db,
        event_type="BOOKING_DELETED",
        booking=None,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        old_values=audit_service.snapshot(booking) | {"booking_reference": booking.booking_reference},
    )
    db.delete(booking)
    db.commit()


def find_bookings_for_owner(db: Session, email: str, pin: str) -> list[DeploymentBooking]:
    candidates = db.scalars(
        select(DeploymentBooking)
        .where(func.lower(DeploymentBooking.requester_email) == email.strip().lower())
        .order_by(DeploymentBooking.deployment_date.desc(), DeploymentBooking.slot_number)
    ).all()
    return [b for b in candidates if verify_secret(pin, b.booking_pin_hash)]


def slot_labels(db: Session, booking: DeploymentBooking) -> tuple[str, str]:
    slot = schedule_service.find_slot(db, booking.deployment_date, booking.slot_number)
    if slot is None:
        return f"Slot {booking.slot_number}", ""
    return slot.name, f"{format_time(slot.start_time)} - {format_time(slot.end_time)}"


def success_message(db: Session, booking: DeploymentBooking) -> str:
    name, times = slot_labels(db, booking)
    return (
        "Deployment slot booked successfully.\n"
        f"Booking Reference: {booking.booking_reference}\n"
        f"{booking.deployment_date.strftime('%A')} {format_day(booking.deployment_date)}\n"
        f"{name} {times}\n"
        f"Tenant: {booking.tenant_name}\n"
        "Important: keep your Booking PIN safe. You will need it to modify or cancel this booking."
    )


def attachment_count(booking: DeploymentBooking, category: str) -> int:
    return sum(1 for a in booking.attachments if a.category == category)


def can_add_attachment(booking: DeploymentBooking, category: str) -> bool:
    if category in MULTI_FILE_CATEGORIES:
        return True
    return attachment_count(booking, category) == 0


def attachment_of(booking: DeploymentBooking, attachment_id: int) -> BookingAttachment | None:
    return next((a for a in booking.attachments if a.id == attachment_id), None)
