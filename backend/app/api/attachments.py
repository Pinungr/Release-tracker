"""Authenticated document upload, download, and removal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BookingStatus, DeploymentBooking, DocumentCategory
from ..schemas import BookingDetail
from ..security import AdminPrincipal, UserPrincipal
from ..services import attachment_service, booking_service, presenters
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from ..utils import files as file_utils
from .deps import current_admin, current_user, get_booking

router = APIRouter(prefix="/bookings", tags=["attachments"])


def _actor(
    booking: DeploymentBooking,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
) -> Actor:
    if admin is not None:
        return Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    if booking.created_by_user_id != user.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not authorized to modify these documents.")
    if booking.status == BookingStatus.CANCELLED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This booking has been cancelled.")
    return Actor(is_admin=False, requester_email=user.email, user_id=user.user_id)


@router.post("/{booking_id}/attachments", response_model=BookingDetail)
def upload_attachment(
    category: DocumentCategory = Form(...),
    file: UploadFile = File(...),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _actor(booking, admin, user)
    if not actor.is_admin and booking_service.is_locked_for_owner(db, booking):
        settings = get_app_settings(db)
        raise HTTPException(status.HTTP_423_LOCKED, f"Changes are disabled within {settings.booking_freeze_hours} hours of deployment.")
    attachment_service.save_upload(db, booking, category, file, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)


@router.delete("/{booking_id}/attachments/{attachment_id}", response_model=BookingDetail)
def delete_attachment(
    attachment_id: int,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _actor(booking, admin, user)
    attachment = booking_service.attachment_of(booking, attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    attachment_service.delete_attachment(db, booking, attachment, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin)


@router.get("/{booking_id}/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> FileResponse:
    if admin is None:
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
        if booking.created_by_user_id != user.user_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You are not authorized to download this document."
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
    return FileResponse(path, media_type="application/octet-stream", filename=attachment.original_filename, headers={"X-Content-Type-Options": "nosniff"})
