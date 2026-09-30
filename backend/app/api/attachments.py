"""Authenticated document upload, download, and removal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeploymentBooking
from ..schemas import AttachmentBulkDelete, BookingDetail
from ..security import AdminPrincipal, UserPrincipal
from ..services import attachment_service, booking_service, document_type_service, presenters
from ..services.booking_service import Actor
from ..services.settings_service import get_app_settings
from ..utils import files as file_utils
from .deps import current_admin, current_user, get_booking

router = APIRouter(prefix="/bookings", tags=["attachments"])


def _attachment_actor(
    db: Session,
    booking: DeploymentBooking,
    admin: AdminPrincipal | None,
    user: UserPrincipal | None,
    *,
    upload: bool = False,
) -> Actor:
    """Uploads may use a recent follow-up unlock; deletion follows scheduling protection."""
    actor = booking_service.schedule_actor(db, booking, admin=admin, user=user)
    if upload:
        error = booking_service.attachment_upload_restriction(db, booking, actor)
        if error is not None:
            raise error
    else:
        booking_service.assert_booking_mutable(db, booking, actor)
    return actor


@router.post("/{booking_id}/attachments", response_model=BookingDetail)
def upload_attachment(
    category: str = Form(..., max_length=40),
    file: list[UploadFile] = File(...),
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    """Upload one file, or several for a Multiple Files document type.

    Repeat the ``file`` field to send several files in one request. For a
    Single File type the upload normally replaces the file already attached;
    protected-date follow-up uploads may only fill a missing type or append to
    a Multiple Files type.
    """
    try:
        actor = _attachment_actor(db, booking, admin, user, upload=True)
        doc_type = document_type_service.uploadable(db, category)
        attachment_service.save_uploads(db, booking, doc_type, file, actor, append_only=booking_service.is_current_or_past_deployment(booking.deployment_date))
    finally:
        for upload in file:
            upload.file.close()
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.delete("/{booking_id}/attachments/{attachment_id}", response_model=BookingDetail)
def delete_attachment(
    attachment_id: int,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    actor = _attachment_actor(db, booking, admin, user)
    attachment_service.delete_attachments(db, booking, [attachment_id], actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.post("/{booking_id}/attachments/bulk-delete", response_model=BookingDetail)
def delete_selected_attachments(
    payload: AttachmentBulkDelete,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> BookingDetail:
    """Delete exactly the selected files; all of them or, on any refusal, none."""
    actor = _attachment_actor(db, booking, admin, user)
    attachment_service.delete_attachments(db, booking, payload.attachment_ids, actor)
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=actor.is_admin, user_id=actor.user_id)


@router.get("/{booking_id}/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal | None = Depends(current_admin),
    user: UserPrincipal | None = Depends(current_user),
) -> FileResponse:
    # Reading a change record includes its documents, and every change record
    # is readable by any signed-in user. Files of since-disabled document types
    # stay downloadable. Recent unlocks permit append-only uploads; removal
    # continues to follow scheduling protection.
    if admin is None and user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
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
