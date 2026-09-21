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
    AssignedUserOut,
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
        tenant_id=booking.tenant_id,
        tenant_name=booking.tenant_name,
        deployment_date=booking.deployment_date,
        slot_number=booking.slot_number,
        jira_number=booking.jira_number,
        jira_url=booking.jira_url,
        change_number=booking.change_number,
        technology=booking.technology,
        environment=booking.environment,
        verifier_name=booking.verifier_name,
        status=booking.status,
        is_emergency=booking.is_emergency,
        created_by_user_id=booking.created_by_user_id,
        assigned_users=[
            AssignedUserOut(
                user_id=a.user_id,
                full_name=a.user.full_name,
                username=a.user.username,
                email=a.user.email,
                assigned_at=a.assigned_at,
            )
            for a in sorted(booking.assignments, key=lambda item: item.id)
        ],
        work_started_by_user_id=booking.work_started_by_user_id,
        work_started_at=booking.work_started_at,
        is_past=booking.deployment_date < today_local(),
        is_locked=booking_service.is_locked_for_owner(db, booking, app_settings),
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
    automatically_frozen = (
        not booking.is_emergency
        and booking_service.is_date_automatically_frozen(db, booking.deployment_date, app_settings)
    )
    can_edit = (
        active
        and booking.deployment_date > today_local()
        and not automatically_frozen
        and (is_admin or (not base["is_locked"] and not booking.is_emergency))
    )
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
        attachments=[attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)],
        can_edit=can_edit,
        slot_label=slot_label,
        slot_time=slot_time,
    )


def public_settings(app_settings: AppSettings) -> PublicSettings:
    return PublicSettings(
        weekly_booking_limit=app_settings.weekly_booking_limit,
        booking_freeze_dates=app_settings.booking_freeze_dates,
        jira_required_at_booking=app_settings.jira_required_at_booking,
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


def _slot_state(
    slot: schedule_service.ResolvedSlot, has_booking: bool, on_holiday: bool, is_past: bool
) -> str:
    if has_booking:
        return "BOOKED"
    if not slot.enabled:
        return "DISABLED"
    if slot.unavailable_reason:
        return "HOLIDAY" if on_holiday else "DISABLED"
    # A free slot on a past date is closed, not available.
    return "DISABLED" if is_past else "AVAILABLE"


def schedule_response(
    db: Session, any_day: date, *, is_admin: bool = False
) -> ScheduleResponse:
    sunday, plans, app_settings = schedule_service.resolve_week(
        db, any_day, include_weekend=is_admin
    )
    end_of_view = sunday + timedelta(days=4)
    bookings = schedule_service.active_bookings_between(db, sunday, end_of_view)
    emergency_bookings = schedule_service.emergency_bookings_between(db, sunday, end_of_view)
    by_cell: dict[tuple[date, int], DeploymentBooking] = {
        (b.deployment_date, b.slot_number): b
        for b in bookings
        if not b.is_emergency and b.slot_number is not None
    }
    emergency_by_day: dict[date, list[DeploymentBooking]] = {}
    for booking in emergency_bookings:
        emergency_by_day.setdefault(booking.deployment_date, []).append(booking)

    today = today_local()
    automatic_freezes = booking_service.automatic_frozen_dates(db, app_settings)
    manual_freezes = booking_service.slot_freezes_between(db, sunday, end_of_view)
    days: list[DayView] = []
    regular_capacity = regular_booked = emergency_total = holiday_count = 0

    for plan in plans:
        slot_views: list[SlotView] = []
        day_regular_total = day_regular_used = 0
        on_holiday = plan.holiday is not None and plan.holiday.is_full_day
        if plan.holiday is not None:
            holiday_count += 1

        for slot in plan.slots:
            booking = by_cell.get((plan.day, slot.slot_number))
            manually_frozen = (plan.day, slot.slot_number) in manual_freezes
            current_or_past = plan.day <= today
            automatically_frozen = plan.day in automatic_freezes
            closed_for_view = current_or_past or automatically_frozen or (
                not is_admin and manually_frozen
            )
            state = _slot_state(slot, booking is not None, on_holiday, closed_for_view)
            open_for_booking = plan.day > today and (
                is_admin
                or (
                    slot.enabled
                    and slot.unavailable_reason is None
                    and not automatically_frozen
                    and not manually_frozen
                )
            )
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
                    enabled=slot.enabled,
                    unavailable_reason=(
                        slot.unavailable_reason
                        or (
                            "Past and current deployment dates are read-only."
                            if current_or_past
                            else None
                        )
                        or (
                            "Inside the configured upcoming-date freeze window."
                            if automatically_frozen
                            else None
                        )
                        or (
                            "Manually frozen by an administrator."
                            if manually_frozen and not is_admin
                            else None
                        )
                    ),
                    state=state,  # type: ignore[arg-type]
                    bookable=(
                        booking is None
                        and plan.day > today
                        and not automatically_frozen
                        and (
                            is_admin
                            or (slot.bookable and not manually_frozen)
                        )
                    ),
                    manually_frozen=manually_frozen,
                    booking=booking_summary(db, booking, app_settings) if booking else None,
                )
            )

        day_emergency = emergency_by_day.get(plan.day, [])
        emergency_total += len(day_emergency)

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
                emergency_open=(
                    plan.day > today and (True if is_admin else plan.emergency_open)
                ),
                emergency_closed_reason=(
                    "Past and current deployment dates are read-only."
                    if plan.day <= today
                    else (None if is_admin else plan.emergency_closed_reason)
                ),
                emergency_bookings=[
                    booking_summary(db, item, app_settings) for item in day_emergency
                ],
            )
        )

    return ScheduleResponse(
        week_start=sunday,
        week_end=end_of_view,
        week_label=format_week_range(sunday),
        today=today,
        timezone=app_config.timezone,
        days=days,
        summary=ScheduleSummary(
            regular_slots_total=regular_capacity,
            regular_slots_available=max(regular_capacity - regular_booked, 0),
            slots_booked=regular_booked,
            holidays=holiday_count,
            emergency_changes=emergency_total,
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
        "booking_freeze_dates": s.booking_freeze_dates,
        "jira_required_at_booking": s.jira_required_at_booking,
        "max_file_size_mb": s.max_file_size_mb,
        "emergency_changes_enabled": s.emergency_changes_enabled,
        "require_admin_override_reason": s.require_admin_override_reason,
        "mandatory_documents": list(s.mandatory_documents),
    }
