"""Public booking endpoints.

Ownership is *always* re-verified here against the stored PIN hash (or the
opaque manage token); the frontend's view of who owns what is never trusted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeploymentBooking
from ..schemas import (
    AttachmentOut,
    BookingCancel,
    BookingCreate,
    BookingCreated,
    BookingDetail,
    BookingSummary,
    BookingUpdate,
    MyBookingsRequest,
    OwnerCredentials,
)
from ..models import Tenant
from ..security import AdminPrincipal, UserPrincipal, generate_manage_token, hash_manage_token
from ..security.ratelimit import enforce
from ..services import booking_service, presenters
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from .deps import current_admin, current_user, get_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])

INVALID_OWNER = "Incorrect requester email or booking PIN."


def _rotate_manage_token(db: Session, booking: DeploymentBooking) -> str:
    token = generate_manage_token()
    booking.manage_token_hash = hash_manage_token(token)
    db.commit()
    return token


def _owner_actor(
    request: Request,
    db: Session,
    booking: DeploymentBooking,
    credentials: OwnerCredentials | None,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> Actor:
    if admin is not None:
        return Actor(is_admin=True, admin_username=admin.username)
    if user is not None:
        if booking.requester_email and booking.requester_email.lower() == user.email.lower():
            return Actor(is_admin=False, requester_email=str(user.email))
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are not authorized to modify this booking.",
        )
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Requester email and booking PIN are required to modify this booking.",
        )
    enforce(request, "verify-owner", limit=10, window_seconds=300)
    if not booking_service.verify_owner(booking, str(credentials.requester_email), credentials.booking_pin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, INVALID_OWNER)
    return Actor(is_admin=False, requester_email=str(credentials.requester_email))


@router.post("", response_model=BookingCreated, status_code=status.HTTP_201_CREATED)
def create_booking(
    request: Request,
    payload: BookingCreate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
) -> BookingCreated:
    enforce(request, "create-booking", limit=20, window_seconds=300)
    actor = (
        Actor(is_admin=True, admin_username=admin.username)
        if admin
        else Actor(is_admin=False, requester_email=str(payload.requester_email))
    )
    booking, manage_token = booking_service.create_booking(db, payload, actor)
    detail = presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)
    return BookingCreated(
        booking=detail,
        manage_token=manage_token,
        manage_url=f"/booking/manage/{manage_token}",
        message=booking_service.success_message(db, booking),
    )


@router.get("/{booking_id}", response_model=BookingDetail)
def read_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
) -> BookingDetail:
    detail = presenters.booking_detail(db, booking, get_app_settings(db), is_admin=admin is not None)
    return detail if admin else presenters.redact_contacts(detail)


@router.post("/{booking_id}/verify-owner", response_model=BookingCreated)
def verify_owner(
    request: Request,
    credentials: OwnerCredentials,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
) -> BookingCreated:
    """Exchanges email + PIN for the unredacted booking and a fresh manage token."""
    enforce(request, "verify-owner", limit=10, window_seconds=300)
    if not booking_service.verify_owner(booking, str(credentials.requester_email), credentials.booking_pin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, INVALID_OWNER)
    token = _rotate_manage_token(db, booking)
    return BookingCreated(
        booking=presenters.booking_detail(db, booking, get_app_settings(db), is_admin=False),
        manage_token=token,
        manage_url=f"/booking/manage/{token}",
        message="Ownership verified.",
    )


@router.get("/manage/token/{token}", response_model=BookingDetail)
def read_booking_by_token(token: str, db: Session = Depends(get_db)) -> BookingDetail:
    booking = booking_service.booking_for_manage_token(db, token)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This management link is no longer valid.")
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=False)


@router.put("/{booking_id}", response_model=BookingDetail)
def update_booking(
    request: Request,
    payload: BookingUpdate,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _owner_actor(request, db, booking, payload.credentials, admin, user)
    booking = booking_service.update_booking(db, booking, payload, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)


@router.delete("/{booking_id}", response_model=BookingSummary)
def cancel_booking(
    request: Request,
    payload: BookingCancel,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingSummary:
    actor = _owner_actor(request, db, booking, payload.credentials, admin, user)
    booking = booking_service.cancel_booking(db, booking, actor, payload.override_reason)
    return presenters.booking_summary(db, booking, get_app_settings(db))


@router.get("/{booking_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(booking: DeploymentBooking = Depends(get_booking)) -> list[AttachmentOut]:
    """Metadata only — file bytes require ownership or admin (see /download)."""
    return [presenters.attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)]


my_bookings_router = APIRouter(tags=["bookings"])


@my_bookings_router.post("/my-bookings", response_model=list[BookingDetail])
def my_bookings(
    request: Request,
    payload: MyBookingsRequest,
    db: Session = Depends(get_db),
) -> list[BookingDetail]:
    enforce(request, "my-bookings", limit=10, window_seconds=300)
    bookings = booking_service.find_bookings_for_owner(
        db, str(payload.requester_email), payload.booking_pin
    )
    app_settings = get_app_settings(db)
    return [presenters.booking_detail(db, b, app_settings, is_admin=False) for b in bookings]
