"""Attachment upload / download / removal."""
from __future__ import annotations

import shutil

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..models import (
    DOCUMENT_LABELS,
    MULTI_FILE_CATEGORIES,
    BookingAttachment,
    DeploymentBooking,
    DocumentCategory,
)
from ..utils import files as file_utils
from . import audit_service
from .booking_service import Actor, BusinessRuleError
from .settings_service import get_app_settings

CHUNK = 1024 * 1024


def save_upload(
    db: Session,
    booking: DeploymentBooking,
    category: DocumentCategory,
    upload: UploadFile,
    actor: Actor,
    *,
    commit: bool = True,
) -> BookingAttachment:
    app_settings = get_app_settings(db)
    raw_name = upload.filename or ""
    if not raw_name.strip():
        raise BusinessRuleError("No file was supplied.")
    if not file_utils.is_allowed_extension(raw_name):
        raise BusinessRuleError(
            "Unsupported file type. Allowed formats: "
            + ", ".join(sorted(file_utils.ALLOWED_EXTENSIONS))
        )

    display_name = file_utils.sanitize_filename(raw_name)
    stored_name = file_utils.build_stored_name(raw_name)
    target = file_utils.attachment_path(booking.id, category.value, stored_name)

    limit = app_settings.max_file_size_bytes
    written = 0
    try:
        with target.open("wb") as fh:
            while True:
                chunk = upload.file.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise BusinessRuleError(
                        f"File exceeds the {app_settings.max_file_size_mb} MB upload limit.",
                        status.HTTP_413_CONTENT_TOO_LARGE,
                    )
                fh.write(chunk)
    except BusinessRuleError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:  # pragma: no cover - disk failure
        target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not store the file.") from exc

    if written == 0:
        target.unlink(missing_ok=True)
        raise BusinessRuleError("The uploaded file is empty.")

    # Single-file categories keep only the latest version.
    if category.value not in MULTI_FILE_CATEGORIES:
        for existing in [a for a in booking.attachments if a.category == category.value]:
            _remove_file(existing)
            db.delete(existing)
        db.flush()

    attachment = BookingAttachment(
        booking_id=booking.id,
        category=category.value,
        original_filename=display_name,
        stored_filename=stored_name,
        content_type=upload.content_type,
        size_bytes=written,
        uploaded_by=actor.admin_username or actor.requester_email,
    )
    db.add(attachment)
    db.flush()
    audit_service.record(
        db,
        event_type="DOCUMENT_ADDED",
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        new_values={"category": DOCUMENT_LABELS[category.value], "filename": display_name},
    )
    if commit:
        db.commit()
        db.refresh(booking)
    else:
        db.flush()
    return attachment


def delete_attachment(
    db: Session, booking: DeploymentBooking, attachment: BookingAttachment, actor: Actor
) -> None:
    _remove_file(attachment)
    db.delete(attachment)
    db.flush()
    audit_service.record(
        db,
        event_type="DOCUMENT_DELETED",
        booking=booking,
        actor_type=actor.actor_type,
        requester_email=booking.requester_email,
        admin_username=actor.admin_username,
        old_values={
            "category": DOCUMENT_LABELS[attachment.category],
            "filename": attachment.original_filename,
        },
    )
    db.commit()
    db.refresh(booking)


def _remove_file(attachment: BookingAttachment) -> None:
    try:
        path = file_utils.attachment_path(
            attachment.booking_id, attachment.category, attachment.stored_filename
        )
        path.unlink(missing_ok=True)
    except (ValueError, OSError):  # pragma: no cover - defensive
        pass


def remove_booking_directory(booking_id: int) -> None:
    root = file_utils.storage_root() / str(int(booking_id))
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
