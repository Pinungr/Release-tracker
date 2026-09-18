"""Attachment upload / download.

Uploads require ownership (email + PIN) or an admin session. Downloads require
an admin session or the booking's opaque manage token, and are always served
as an attachment with a generic content type so nothing can be executed or
rendered inline by the browser.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BookingStatus, DeploymentBooking, DocumentCategory
from ..schemas import BookingDetail, OwnerCredentials
from ..security import AdminPrincipal
from ..security.ratelimit import enforce
from ..services import attachment_service, booking_service, presenters
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from ..utils import files as file_utils
from .bookings import INVALID_OWNER
from .deps import current_admin, get_booking

router = APIRouter(prefix="/bookings", tags=["attachments"])


def _upload_actor(
    request: Request,
    booking: DeploymentBooking,
    db: Session,
    admin: AdminPrincipal | None,
    requester_email: str | None,
    booking_pin: str | None,
) -> Actor:
    if admin is not None:
        return Actor(is_admin=True, admin_username=admin.username)
    if not requester_email or not booking_pin:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Requester email and booking PIN are required."
        )
    enforce(request, "verify-owner", limit=10, window_seconds=300)
    if not booking_service.verify_owner(booking, requester_email, booking_pin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, INVALID_OWNER)
    if booking.status == BookingStatus.CANCELLED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This booking has been cancelled.")
    if booking_service.is_locked_for_public(db, booking):
        app_settings = get_app_settings(db)
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Changes are disabled within {app_settings.booking_freeze_hours} hours of the "
            "deployment. Contact an administrator for assistance.",
        )
    return Actor(is_admin=False, requester_email=requester_email)


@router.post("/{booking_id}/attachments", response_model=BookingDetail)
def upload_attachment(
    request: Request,
    category: DocumentCategory = Form(...),
    file: UploadFile = File(...),
    requester_email: str | None = Form(default=None),
    booking_pin: str | None = Form(default=None),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
) -> BookingDetail:
    actor = _upload_actor(request, booking, db, admin, requester_email, booking_pin)
    attachment_service.save_upload(db, booking, category, file, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)


@router.delete("/{booking_id}/attachments/{attachment_id}", response_model=BookingDetail)
def delete_attachment(
    request: Request,
    attachment_id: int,
    # Credentials travel in the body, never in the query string, so a booking
    # PIN cannot end up in an access log or the browser history.
    credentials: OwnerCredentials | None = Body(default=None, embed=False),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
) -> BookingDetail:
    actor = _upload_actor(
        request,
        booking,
        db,
        admin,
        str(credentials.requester_email) if credentials else None,
        credentials.booking_pin if credentials else None,
    )
    attachment = booking_service.attachment_of(booking, attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    attachment_service.delete_attachment(db, booking, attachment, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)


@router.get("/{booking_id}/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    token: str | None = None,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
) -> FileResponse:
    if admin is None:
        owner = booking_service.booking_for_manage_token(db, token or "")
        if owner is None or owner.id != booking.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Verify the booking PIN before downloading deployment documents.",
            )
    attachment = booking_service.attachment_of(booking, attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    try:
        path = file_utils.attachment_path(booking.id, attachment.category, attachment.stored_filename)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid attachment path.") from None
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "The stored file is no longer available.")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=attachment.original_filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )
