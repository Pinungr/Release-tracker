"""Mapping of ORM entities onto the API response schemas."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from ..config import settings as app_config
from ..models import (
    DOCUMENT_LABELS,
    BookingAudit,
    BookingAttachment,
    BookingStatus,
    BookingCollaborator,
    DeploymentBooking,
    User,
    DocumentCategory,
    Technology,
)
from ..schemas.booking import (
    AssignedUserOut,
    AttachmentOut,
    AuditEventOut,
    BookingDetail,
    BookingSummary,
    DayView,
    HolidayOut,
    PublicSettings,
    ScheduleResponse,
    ScheduleSummary,
    SlotOptionOut,
    SlotView,
)
from ..utils.dates import WEEKDAY_NAMES, format_day, format_time, format_week_range, today_local
from . import booking_service, group_service, schedule_service
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
        lock_reason=booking_service.booking_lock_reason(db, booking, app_settings),
        is_locked=booking_service.is_locked_for_owner(db, booking, app_settings),
        documents=booking_service.document_readiness(booking, app_settings),
        created_at=booking.created_at,
        updated_at=booking.updated_at,
    )


def booking_detail(
    db: Session, booking: DeploymentBooking, app_settings: AppSettings, *, is_admin: bool, user_id: int | None = None
) -> BookingDetail:
    base = booking_summary(db, booking, app_settings).model_dump()
    slot_label, slot_time = booking_service.slot_labels(db, booking)
    active = booking.status != BookingStatus.CANCELLED.value
    date_mutable = base["lock_reason"] not in {"CURRENT_DATE", "PAST_DATE", "AUTOMATIC_DATE_FREEZE"}
    mutable = active and date_mutable and (is_admin or not base["is_locked"])
    owner = user_id is not None and user_id == booking.created_by_user_id
    collaborator = user_id is not None and booking_service.user_is_collaborator(db, booking, user_id)
    assigned = user_id is not None and booking_service.user_is_assigned(booking, user_id)
    account = db.get(User, user_id) if user_id is not None else None
    is_release_manager = (
        account is not None
        and account.is_active
        and not account.is_owner
        and group_service.is_release_manager(db, account.id)
    )
    can_edit = mutable and (is_admin or ((owner or collaborator) and not booking.is_emergency))
    from ..models import BookingAudit
    from sqlalchemy import select
    import json
    clone_event = db.scalars(select(BookingAudit).where(
        BookingAudit.booking_id == booking.id, BookingAudit.event_type == "BOOKING_CLONED"
    ).order_by(BookingAudit.id).limit(1)).first()
    clone = json.loads(clone_event.new_values or "{}") if clone_event else {}
    return BookingDetail(
        cloned_from_id=clone.get("source_id"),
        cloned_from_reference=clone.get("source_reference"),
        **base,
        requester_name=booking.requester_name,
        requester_email=booking.requester_email,
        requester_phone=booking.requester_phone,
        verifier_email=booking.verifier_email,
        git_repository=booking.git_repository,
        implementation_summary=booking.implementation_summary,
        deployment_description=booking.deployment_description,
        additional_comments=booking.additional_comments,
        justification=booking.justification,
        impacted_region=booking.impacted_region,
        emergency_reason=booking.emergency_reason,
        emergency_approval_reference=booking.emergency_approval_reference,
        emergency_approver=booking.emergency_approver,
        business_justification=booking.business_justification,
        cancelled_at=booking.cancelled_at,
        cancelled_by_user_id=booking.cancelled_by_user_id,
        attachments=[attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)],
        collaborators=[
            AssignedUserOut(
                user_id=row.user_id,
                full_name=user.full_name,
                username=user.username,
                email=user.email,
                assigned_at=row.created_at,
            )
            for row, user in db.execute(
                select(BookingCollaborator, User)
                .join(User, User.id == BookingCollaborator.user_id)
                .where(BookingCollaborator.booking_id == booking.id)
                .order_by(User.full_name, User.username)
            ).all()
        ],
        can_edit=can_edit,
        can_cancel=can_edit and booking.status != BookingStatus.COMPLETED.value,
        can_reschedule=can_edit and booking.status != BookingStatus.COMPLETED.value,
        can_assign_rm=mutable and is_admin and booking.status != BookingStatus.COMPLETED.value,
        can_assign_self=mutable and is_release_manager and (not assigned or len(booking.assignments) > 1) and booking.status != BookingStatus.COMPLETED.value,
        can_start_work=mutable and assigned and is_release_manager and booking.status in {BookingStatus.BOOKED.value, BookingStatus.IN_PROGRESS.value},
        # Every signed-in user can read any change record, documents included.
        can_download_attachments=True,
        can_manage_attachments=can_edit,
        slot_label=slot_label,
        slot_time=slot_time,
    )


def slot_option_out(option: booking_service.SlotOption) -> SlotOptionOut:
    return SlotOptionOut(
        deployment_date=option.deployment_date,
        weekday=WEEKDAY_NAMES[option.deployment_date.weekday()],
        date_label=format_day(option.deployment_date),
        slot_number=option.slot_number,
        slot_name=option.slot_name,
        time_label=f"{format_time(option.start_time)} - {format_time(option.end_time)}",
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
    sunday, plans, app_settings = schedule_service.resolve_week(db, any_day)
    end_of_view = plans[-1].day
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
            rejection = booking_service.normal_slot_rejection(
                plan.day, slot, today=today, frozen_dates=automatic_freezes,
                manually_frozen=manually_frozen,
            )
            open_for_booking = rejection is None
            state = _slot_state(slot, booking is not None, on_holiday, not open_for_booking)
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
                    unavailable_reason=rejection[0] if rejection else None,
                    state=state,  # type: ignore[arg-type]
                    bookable=booking is None and open_for_booking,
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
                custom_slot_count=plan.custom_slot_count,
                regular_slots_total=day_regular_total,
                regular_slots_used=day_regular_used,
                slots=slot_views,
                emergency_open=(
                    plan.day > today and plan.day not in automatic_freezes and (True if is_admin else plan.emergency_open)
                ),
                emergency_closed_reason=(
                    "Past and current deployment dates are read-only."
                    if plan.day <= today
                    else (booking_service.AUTOMATIC_FREEZE_MESSAGE if plan.day in automatic_freezes else (None if is_admin else plan.emergency_closed_reason))
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
        actor_type="USER" if event.actor_type == "TENANT_USER" else event.actor_type,  # type: ignore[arg-type]
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
        "mandatory_documents": list(s.mandatory_documents),
    }
