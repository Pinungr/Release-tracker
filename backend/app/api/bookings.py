"""Authenticated booking endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeploymentBooking
from ..schemas import AttachmentOut, BookingCancel, BookingCreate, BookingCreated, BookingDetail, BookingSummary, BookingUpdate
from ..security import AdminPrincipal, UserPrincipal
from ..security.ratelimit import enforce
from ..services import booking_service, presenters
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
    if booking.created_by_user_id != user.user_id:
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
def create_booking(
    request: Request,
    payload: BookingCreate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingCreated:
    enforce(request, "create-booking", limit=20, window_seconds=300)
    if admin is not None:
        actor = Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    elif user is not None:
        actor = Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    booking = booking_service.create_booking(db, payload, actor)
    detail = presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)
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
        db, booking, get_app_settings(db), is_admin=admin is not None
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
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=actor.is_admin)


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


@router.get("/{booking_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    booking: DeploymentBooking = Depends(get_booking),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> list[AttachmentOut]:
    _assert_can_view(booking, admin, user)
    return [presenters.attachment_out(a) for a in sorted(booking.attachments, key=lambda a: a.id)]
