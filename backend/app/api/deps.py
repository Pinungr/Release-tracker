"""Shared router dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeploymentBooking
from ..security import AdminPrincipal, UserPrincipal, optional_admin, optional_user
from ..services.booking_service import Actor


def get_booking(
    booking_id: int = Path(ge=1), db: Session = Depends(get_db)
) -> DeploymentBooking:
    booking = db.get(DeploymentBooking, booking_id)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found.")
    return booking


def admin_actor(admin: AdminPrincipal) -> Actor:
    return Actor(is_admin=True, admin_username=admin.username)


def public_actor(requester_email: str | None = None) -> Actor:
    return Actor(is_admin=False, requester_email=requester_email)


def current_admin(admin: AdminPrincipal | None = Depends(optional_admin)) -> AdminPrincipal | None:
    return admin


def current_user(user: UserPrincipal | None = Depends(optional_user)) -> UserPrincipal | None:
    return user
