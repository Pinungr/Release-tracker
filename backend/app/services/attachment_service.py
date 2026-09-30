"""Attachment upload / removal.

Each uploaded file is its own ``BookingAttachment`` row. The document type
decides the rules, enforced here rather than in the browser:

* Single File types hold at most one file per schedule; a new upload replaces it.
* Multiple Files types accept several files per upload and more later.
* A Required type can never be left empty by a deletion.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..models import BookingAttachment, DeploymentBooking, DocumentType
from ..utils import files as file_utils
from . import document_type_service
from .booking_service import Actor, BusinessRuleError, admin_freeze_override_reason, audit
from .settings_service import get_app_settings

CHUNK = 1024 * 1024
#: Upper bound on files accepted in one upload request.
MAX_FILES_PER_UPLOAD = 20


def _store(booking: DeploymentBooking, doc_type: DocumentType, upload: UploadFile, limit: int, limit_mb: int) -> tuple[Path, str, str, int]:
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
    target = file_utils.attachment_path(booking.id, doc_type.key, stored_name)
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
                        f"{display_name} exceeds the {limit_mb} MB upload limit.",
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
        raise BusinessRuleError(f"{display_name} is empty.")
    return target, display_name, stored_name, written


def save_uploads(
    db: Session,
    booking: DeploymentBooking,
    doc_type: DocumentType,
    uploads: list[UploadFile],
    actor: Actor,
    *,
    commit: bool = True,
) -> list[BookingAttachment]:
    """Store every file or none of them.

    For a Single File type the upload replaces whatever is attached, so there
    is never more than one active file for that type on the schedule.
    """
    uploads = [u for u in uploads if u is not None]
    if not uploads:
        raise BusinessRuleError("No file was supplied.")
    if not doc_type.allow_multiple and len(uploads) > 1:
        raise BusinessRuleError(
            f"“{doc_type.label}” accepts a single file. Select one file.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if len(uploads) > MAX_FILES_PER_UPLOAD:
        raise BusinessRuleError(
            f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    app_settings = get_app_settings(db)
    stored: list[tuple[Path, str, str, int, UploadFile]] = []
    try:
        for upload in uploads:
            path, display_name, stored_name, size = _store(
                booking, doc_type, upload, app_settings.max_file_size_bytes, app_settings.max_file_size_mb
            )
            stored.append((path, display_name, stored_name, size, upload))
    except Exception:
        for path, *_ in stored:
            path.unlink(missing_ok=True)
        raise

    replaced: list[BookingAttachment] = []
    if not doc_type.allow_multiple:
        replaced = [a for a in booking.attachments if a.category == doc_type.key]
        replaced_names = ", ".join(a.original_filename for a in replaced)
        replaced_ids = [a.id for a in replaced]
        stale = [_path_of(old) for old in replaced]
        for existing in replaced:
            db.delete(existing)
        db.flush()

    created: list[BookingAttachment] = []
    for _path, display_name, stored_name, size, upload in stored:
        attachment = BookingAttachment(
            booking_id=booking.id,
            category=doc_type.key,
            original_filename=display_name,
            stored_filename=stored_name,
            content_type=upload.content_type,
            size_bytes=size,
            uploaded_by=actor.admin_username or actor.requester_email,
        )
        db.add(attachment)
        created.append(attachment)
    db.flush()

    # Admin/RM acting on a manually frozen slot leave the same audited
    # override reason as schedule edits, cancellations and reschedules.
    override = admin_freeze_override_reason(db, booking, actor, None)
    if replaced:
        audit(
            db, actor, "DOCUMENT_REPLACED", booking,
            override_reason=override,
            old_values={"category": doc_type.label, "filename": replaced_names, "attachment_ids": replaced_ids},
            new_values={
                "category": doc_type.label,
                "filename": created[0].original_filename,
                "attachment_id": created[0].id,
            },
        )
    else:
        for attachment in created:
            audit(
                db, actor, "DOCUMENT_ADDED", booking,
                override_reason=override,
                new_values={
                    "category": doc_type.label,
                    "filename": attachment.original_filename,
                    "attachment_id": attachment.id,
                },
            )

    if commit:
        db.commit()
        db.refresh(booking)
        if replaced:
            _unlink(stale)
    else:
        db.flush()
    return created


def delete_attachments(
    db: Session,
    booking: DeploymentBooking,
    attachment_ids: list[int],
    actor: Actor,
) -> None:
    """Delete exactly the selected files, all or nothing.

    Other files in the same document type are untouched. A deletion that would
    leave an active Required type with no file is refused; upload a
    replacement first (a Single File upload replaces in one step).
    """
    unique_ids = list(dict.fromkeys(attachment_ids))
    if not unique_ids:
        raise BusinessRuleError("Select at least one file to delete.", status.HTTP_422_UNPROCESSABLE_CONTENT)
    by_id = {a.id: a for a in booking.attachments}
    missing = [i for i in unique_ids if i not in by_id]
    if missing:
        raise BusinessRuleError("Attachment not found.", status.HTTP_404_NOT_FOUND)
    selected = [by_id[i] for i in unique_ids]

    doc_types = {t.key: t for t in document_type_service.all_types(db)}
    for key in {a.category for a in selected}:
        doc_type = doc_types.get(key)
        if doc_type is None or not (doc_type.is_active and doc_type.is_required):
            continue
        remaining = sum(1 for a in booking.attachments if a.category == key) - sum(
            1 for a in selected if a.category == key
        )
        if remaining < 1:
            raise BusinessRuleError(
                f"“{doc_type.label}” is required, so at least one file must remain. "
                "Upload a replacement before deleting the last file.",
                status.HTTP_409_CONFLICT,
            )

    labels = {key: t.label for key, t in doc_types.items()}
    removed = [
        {"category": labels.get(a.category, a.category), "filename": a.original_filename, "attachment_id": a.id}
        for a in selected
    ]
    override = admin_freeze_override_reason(db, booking, actor, None)
    stale = [_path_of(a) for a in selected]
    for attachment in selected:
        db.delete(attachment)
    db.flush()
    if len(removed) == 1:
        audit(db, actor, "DOCUMENT_DELETED", booking, override_reason=override, old_values=removed[0])
    else:
        # Filenames for people, attachment ids so duplicate names stay unambiguous.
        audit(
            db, actor, "DOCUMENTS_DELETED", booking,
            override_reason=override,
            old_values={
                "files": [f"{r['filename']} ({r['category']})" for r in removed],
                "attachment_ids": [r["attachment_id"] for r in removed],
                "count": len(removed),
            },
        )
    db.commit()
    db.refresh(booking)
    _unlink(stale)


def _path_of(attachment: BookingAttachment) -> Path | None:
    try:
        return file_utils.attachment_path(
            attachment.booking_id, attachment.category, attachment.stored_filename
        )
    except ValueError:  # pragma: no cover - defensive
        return None


def _unlink(paths: list[Path | None]) -> None:
    """Remove stored files only after the database change is committed."""
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            pass


def remove_booking_directory(booking_id: int) -> None:
    root = file_utils.storage_root() / str(int(booking_id))
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
