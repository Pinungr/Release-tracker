"""Authenticated booking endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from pydantic import ValidationError as PydanticValidationError
from fastapi.exceptions import RequestValidationError

from ..database import get_db
from ..models import DeploymentBooking, DocumentCategory
from ..schemas import (
    AttachmentOut,
    BookingCancel,
    BookingCreate,
    BookingCreated,
    BookingDetail,
    BookingSummary,
    BookingUpdate,
    RescheduleRequest,
    SlotOptionOut,
    StartWorkRequest,
)
from ..security import AdminPrincipal, UserPrincipal
from ..security.ratelimit import enforce
from ..services import attachment_service, booking_service, presenters
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from .deps import current_admin, current_user, get_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _assert_can_view(
    booking: DeploymentBooking,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> None:
    """Authenticate first, then authorize: 401 before 403."""
    if admin is not None:
        return
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    if booking.created_by_user_id != user.user_id and not booking_service.user_is_assigned(booking, user.user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You are not authorized to view this change record."
        )


def _owner_actor(
    booking: DeploymentBooking,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> Actor:
    if admin is not None:
        return Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    if booking.created_by_user_id != user.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not authorized to modify this booking.")
    return Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)


@router.post("", response_model=BookingCreated, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: Request,
    payload: str = Form(...),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingCreated:
    """Create a booking and its required deployment documents atomically.

    A slot is not considered booked until every document category configured as
    mandatory has been supplied and stored successfully.  This keeps the UI and
    API rules aligned: callers cannot create an incomplete booking by bypassing
    the browser and posting JSON directly.
    """
    enforce(request, "create-booking", limit=20, window_seconds=300)
    if admin is not None:
        actor = Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    elif user is not None:
        actor = Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")

    try:
        booking_payload = BookingCreate.model_validate_json(payload)
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    form = await request.form()
    app_settings = get_app_settings(db)
    uploads: dict[DocumentCategory, list[object]] = {}
    missing: list[str] = []

    for category in DocumentCategory:
        files = [
            item
            for item in form.getlist(f"document_{category.value}")
            if getattr(item, "filename", "")
        ]
        uploads[category] = files
        if category.value in app_settings.mandatory_documents and not files:
            from ..models import DOCUMENT_LABELS
            missing.append(DOCUMENT_LABELS[category.value])

    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Required deployment document missing: " + ", ".join(missing),
        )

    booking: DeploymentBooking | None = None
    try:
        booking = booking_service.create_booking(db, booking_payload, actor, commit=False)
        for category, files in uploads.items():
            for upload in files:
                attachment_service.save_upload(
                    db, booking, category, upload, actor, commit=False  # type: ignore[arg-type]
                )
        db.commit()
        db.refresh(booking)
    except Exception:
        db.rollback()
        if booking is not None and booking.id is not None:
            attachment_service.remove_booking_directory(booking.id)
        raise

    detail = presenters.booking_detail(db, booking, app_settings, is_admin=actor.is_admin, user_id=actor.user_id)
    return BookingCreated(booking=detail, message=booking_service.success_message(db, booking))


@router.get("/{booking_id}", response_model=BookingDetail)
def read_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    _assert_can_view(booking, admin, user)
    return presenters.booking_detail(
        db, booking, get_app_settings(db), is_admin=admin is not None, user_id=user.user_id if user else None
    )


@router.put("/{booking_id}", response_model=BookingDetail)
def update_booking(
    request: Request,
    payload: BookingUpdate,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _owner_actor(booking, admin, user)
    updated = booking_service.update_booking(db, booking, payload, actor)
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.delete("/{booking_id}", response_model=BookingSummary)
def cancel_booking(
    request: Request,
    payload: BookingCancel,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingSummary:
    actor = _owner_actor(booking, admin, user)
    cancelled = booking_service.cancel_booking(db, booking, actor, payload.override_reason)
    return presenters.booking_summary(db, cancelled, get_app_settings(db))


@router.get("/{booking_id}/reschedule-options", response_model=list[SlotOptionOut])
def reschedule_options(
    limit: int = Query(default=12, ge=1, le=100),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> list[SlotOptionOut]:
    """Destinations this caller is allowed to move the booking to.

    Only the owner or an administrator may reschedule, so the same check
    guards the picker: nobody sees availability for a record they cannot move.
    """
    actor = _owner_actor(booking, admin, user)
    return [
        presenters.slot_option_out(option)
        for option in booking_service.next_available_slots(db, booking, actor, limit=limit)
    ]


@router.post("/{booking_id}/reschedule", response_model=BookingDetail)
def reschedule_booking(
    payload: RescheduleRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _owner_actor(booking, admin, user)
    moved = booking_service.reschedule_booking(
        db,
        booking,
        payload.deployment_date,
        payload.slot_number,
        actor,
        payload.override_reason,
    )
    return presenters.booking_detail(db, moved, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.post("/{booking_id}/start-work", response_model=BookingDetail)
def start_work(
    payload: StartWorkRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    if admin is not None:
        actor = Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    elif user is not None:
        actor = Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    updated = booking_service.start_work(db, booking, payload.change_number, actor)
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.get("/{booking_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    booking: DeploymentBooking = Depends(get_booking),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> list[AttachmentOut]:
    _assert_can_view(booking, admin, user)
    return [presenters.attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)]
