"""Mapping of ORM entities onto the API response schemas."""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..config import settings as app_config
from ..models import (
    DOCUMENT_LABELS,
    BookingAudit,
    BookingAttachment,
    BookingStatus,
    DeploymentBooking,
    DocumentCategory,
    Technology,
)
from ..schemas.booking import (
    AttachmentOut,
    AuditEventOut,
    BookingDetail,
    BookingSummary,
    DailyOverrideOut,
    DayView,
    HolidayOut,
    PublicSettings,
    ScheduleResponse,
    ScheduleSummary,
    SlotView,
)
from ..utils.dates import WEEKDAY_NAMES, format_day, format_time, format_week_range, today_local
from . import booking_service, schedule_service
from .settings_service import AppSettings, get_app_settings


def attachment_out(att: BookingAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=att.id,
        category=DocumentCategory(att.category),
        category_label=DOCUMENT_LABELS[att.category],
        original_filename=att.original_filename,
        size_bytes=att.size_bytes,
        content_type=att.content_type,
        uploaded_at=att.uploaded_at,
    )


def booking_summary(db: Session, booking: DeploymentBooking, app_settings: AppSettings) -> BookingSummary:
    return BookingSummary(
        id=booking.id,
        booking_reference=booking.booking_reference,
        tenant_name=booking.tenant_name,
        deployment_date=booking.deployment_date,
        slot_number=booking.slot_number,
        jira_change=booking.jira_change,
        jira_task=booking.jira_task,
        jira_url=booking.jira_url,
        technology=booking.technology,
        environment=booking.environment,
        verifier_name=booking.verifier_name,
        status=booking.status,
        is_emergency=booking.is_emergency,
        is_locked=booking_service.is_locked_for_public(db, booking, app_settings),
        lock_deadline=booking_service.lock_deadline(db, booking, app_settings),
        documents=booking_service.document_readiness(booking, app_settings),
        created_at=booking.created_at,
        updated_at=booking.updated_at,
    )


def booking_detail(
    db: Session, booking: DeploymentBooking, app_settings: AppSettings, *, is_admin: bool
) -> BookingDetail:
    base = booking_summary(db, booking, app_settings).model_dump()
    slot_label, slot_time = booking_service.slot_labels(db, booking)
    active = booking.status != BookingStatus.CANCELLED.value
    can_edit = active and (is_admin or (not base["is_locked"] and not booking.is_emergency))
    return BookingDetail(
        **base,
        requester_name=booking.requester_name,
        requester_email=booking.requester_email,
        requester_phone=booking.requester_phone,
        verifier_email=booking.verifier_email,
        git_repository=booking.git_repository,
        implementation_summary=booking.implementation_summary,
        deployment_description=booking.deployment_description,
        additional_comments=booking.additional_comments,
        emergency_reason=booking.emergency_reason,
        emergency_approval_reference=booking.emergency_approval_reference,
        emergency_approver=booking.emergency_approver,
        business_justification=booking.business_justification,
        cancelled_at=booking.cancelled_at,
        created_by_admin=booking.created_by_admin,
        attachments=[attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)],
        can_edit=can_edit,
        slot_label=slot_label,
        slot_time=slot_time,
    )


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, _, domain = value.partition("@")
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}{'*' * max(len(local) - len(keep), 2)}@{domain}"


def mask_phone(value: str | None) -> str | None:
    if not value:
        return value
    digits = [c for c in value if c.isdigit()]
    return f"{'*' * max(len(digits) - 3, 3)}{''.join(digits[-3:])}" if digits else None


def redact_contacts(detail: BookingDetail) -> BookingDetail:
    """Anonymous visitors see who is involved, but not how to reach them."""
    return detail.model_copy(
        update={
            "requester_email": mask_email(detail.requester_email),
            "verifier_email": mask_email(detail.verifier_email),
            "requester_phone": mask_phone(detail.requester_phone),
        }
    )


def public_settings(app_settings: AppSettings) -> PublicSettings:
    return PublicSettings(
        weekly_booking_limit=app_settings.weekly_booking_limit,
        booking_freeze_hours=app_settings.booking_freeze_hours,
        max_file_size_mb=app_settings.max_file_size_mb,
        mandatory_documents=list(app_settings.mandatory_documents),
        document_catalog=[
            {
                "category": c.value,
                "label": DOCUMENT_LABELS[c.value],
                "required": c.value in app_settings.mandatory_documents,
                "multiple": c.value == DocumentCategory.SUPPORTING_DOCUMENTS.value,
            }
            for c in DocumentCategory
        ],
        technologies=[t.value for t in Technology],
    )


def _slot_state(slot: schedule_service.ResolvedSlot, has_booking: bool, on_holiday: bool) -> str:
    if has_booking:
        return "BOOKED"
    if not slot.enabled:
        return "DISABLED"
    if slot.unavailable_reason:
        return "HOLIDAY" if on_holiday else "DISABLED"
    return "EMERGENCY_AVAILABLE" if slot.is_emergency else "AVAILABLE"


def schedule_response(db: Session, any_day: date) -> ScheduleResponse:
    monday, plans, app_settings = schedule_service.resolve_week(db, any_day)
    friday = monday + timedelta(days=4)
    bookings = schedule_service.active_bookings_between(db, monday, friday)
    by_cell: dict[tuple[date, int], DeploymentBooking] = {
        (b.deployment_date, b.slot_number): b for b in bookings
    }

    today = today_local()
    days: list[DayView] = []
    regular_capacity = regular_booked = emergency_capacity = emergency_booked = holiday_count = 0

    for plan in plans:
        slot_views: list[SlotView] = []
        day_regular_total = day_regular_used = 0
        on_holiday = plan.holiday is not None and plan.holiday.is_full_day
        if plan.holiday is not None:
            holiday_count += 1

        for slot in plan.slots:
            booking = by_cell.get((plan.day, slot.slot_number))
            state = _slot_state(slot, booking is not None, on_holiday)
            open_for_booking = slot.enabled and slot.unavailable_reason is None
            if slot.is_emergency:
                if open_for_booking or booking is not None:
                    emergency_capacity += 1
                if booking is not None:
                    emergency_booked += 1
            else:
                if open_for_booking or booking is not None:
                    regular_capacity += 1
                    day_regular_total += 1
                if booking is not None:
                    regular_booked += 1
                    day_regular_used += 1

            slot_views.append(
                SlotView(
                    slot_number=slot.slot_number,
                    name=slot.name,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    time_label=f"{format_time(slot.start_time)} - {format_time(slot.end_time)}",
                    is_emergency=slot.is_emergency,
                    enabled=slot.enabled,
                    unavailable_reason=slot.unavailable_reason,
                    state=state,  # type: ignore[arg-type]
                    bookable_by_public=slot.bookable_by_public and booking is None and plan.day >= today,
                    bookable_by_admin=slot.bookable_by_admin and booking is None and plan.day >= today,
                    booking=booking_summary(db, booking, app_settings) if booking else None,
                )
            )

        days.append(
            DayView(
                day=plan.day,
                weekday=WEEKDAY_NAMES[plan.day.weekday()],
                date_label=format_day(plan.day),
                is_today=plan.day == today,
                is_past=plan.day < today,
                holiday=HolidayOut.model_validate(plan.holiday) if plan.holiday else None,
                override=DailyOverrideOut.model_validate(plan.override) if plan.override else None,
                regular_slots_total=day_regular_total,
                regular_slots_used=day_regular_used,
                slots=slot_views,
            )
        )

    return ScheduleResponse(
        week_start=monday,
        week_end=friday,
        week_label=format_week_range(monday),
        today=today,
        timezone=app_config.timezone,
        days=days,
        summary=ScheduleSummary(
            regular_slots_total=regular_capacity,
            regular_slots_available=max(regular_capacity - regular_booked, 0),
            slots_booked=regular_booked,
            holidays=holiday_count,
            emergency_slots_total=emergency_capacity,
            emergency_slots_booked=emergency_booked,
        ),
        settings=public_settings(app_settings),
    )


def audit_event_out(event: BookingAudit) -> AuditEventOut:
    def _load(raw: str | None) -> dict | None:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    return AuditEventOut(
        id=event.id,
        booking_reference=event.booking_reference,
        event_type=event.event_type,
        actor_type=event.actor_type,  # type: ignore[arg-type]
        requester_email=event.requester_email,
        admin_username=event.admin_username,
        override_reason=event.override_reason,
        old_values=_load(event.old_values),
        new_values=_load(event.new_values),
        created_at=event.created_at,
    )


def settings_out(db: Session) -> dict:
    s = get_app_settings(db)
    return {
        "regular_slots_per_day": s.regular_slots_per_day,
        "weekly_booking_limit": s.weekly_booking_limit,
        "booking_freeze_hours": s.booking_freeze_hours,
        "max_file_size_mb": s.max_file_size_mb,
        "emergency_slot_enabled": s.emergency_slot_enabled,
        "require_admin_override_reason": s.require_admin_override_reason,
        "mandatory_documents": list(s.mandatory_documents),
    }
