"""Admin/RM-configured document upload options.

``DocumentType.key`` is what ``booking_attachments.category`` stores. Keys are
immutable, and a type referenced by an uploaded file is never hard deleted:
disabling it stops new uploads while historical files stay visible and
downloadable.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import BookingAttachment, DocumentType
from . import audit_service

_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")


def all_types(db: Session) -> list[DocumentType]:
    return list(db.scalars(select(DocumentType).order_by(DocumentType.display_order, DocumentType.id)).all())


def active_types(db: Session) -> list[DocumentType]:
    return [t for t in all_types(db) if t.is_active]


def by_key(db: Session, key: str) -> DocumentType | None:
    return db.scalars(select(DocumentType).where(DocumentType.key == key)).first()


def labels(db: Session) -> dict[str, str]:
    return {t.key: t.label for t in all_types(db)}


def usage_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(BookingAttachment.category, func.count(BookingAttachment.id)).group_by(BookingAttachment.category)
    ).all()
    return {category: int(count) for category, count in rows}


def multi_file_schedule_counts(db: Session) -> dict[str, int]:
    """Per type, how many schedules hold more than one file of it.

    Only meaningful for Single File types: a type switched from Multiple to
    Single keeps the files schedules already had (nothing is deleted by the
    switch). The next upload on such a schedule replaces all of them.
    """
    per_booking = (
        select(BookingAttachment.category, BookingAttachment.booking_id)
        .group_by(BookingAttachment.category, BookingAttachment.booking_id)
        .having(func.count(BookingAttachment.id) > 1)
        .subquery()
    )
    rows = db.execute(
        select(per_booking.c.category, func.count()).group_by(per_booking.c.category)
    ).all()
    return {category: int(count) for category, count in rows}


def uploadable(db: Session, key: str) -> DocumentType:
    """The active type an upload targets, or a clear rejection."""
    doc_type = by_key(db, (key or "").strip())
    if doc_type is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select a valid document type.")
    if not doc_type.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{doc_type.label}” is disabled and no longer accepts uploads.",
        )
    return doc_type


def _assert_label_free(db: Session, label: str, *, exclude_id: int | None = None) -> None:
    stmt = select(DocumentType.id).where(func.lower(DocumentType.label) == label.lower())
    if exclude_id is not None:
        stmt = stmt.where(DocumentType.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A document type named “{label}” already exists.")


def _derive_key(db: Session, label: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_") or "DOCUMENT"
    if not base[0].isalpha():
        base = f"DOC_{base}"
    base = base[:36]
    key, suffix = base, 2
    while by_key(db, key) is not None:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def _record(db: Session, admin_username: str, event_type: str, doc_type: DocumentType, old: dict | None, new: dict | None) -> None:
    identity = {"document_type": doc_type.label, "key": doc_type.key}
    audit_service.record(
        db,
        event_type=event_type,
        actor_type="ADMIN",
        admin_username=admin_username,
        old_values=(identity | old) if old is not None else None,
        new_values=(identity | new) if new is not None else identity,
    )


def create(
    db: Session,
    *,
    label: str,
    description: str | None,
    is_required: bool,
    allow_multiple: bool,
    is_active: bool,
    key: str | None,
    user_id: int,
    admin_username: str,
) -> DocumentType:
    label = label.strip()
    _assert_label_free(db, label)
    if key:
        key = key.strip().upper()
        if not _KEY.match(key):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Key must start with a letter and use only A-Z, 0-9 and underscores (2-40 characters).",
            )
        if by_key(db, key) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"The key {key} is already in use.")
    else:
        key = _derive_key(db, label)
    highest = db.scalar(select(func.max(DocumentType.display_order))) or 0
    doc_type = DocumentType(
        key=key,
        label=label,
        description=(description or "").strip() or None,
        is_active=is_active,
        is_required=is_required,
        allow_multiple=allow_multiple,
        display_order=highest + 1,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    db.add(doc_type)
    db.flush()
    _record(db, admin_username, "DOCUMENT_TYPE_CREATED", doc_type, None, {
        "required": is_required,
        "file_mode": "Multiple" if allow_multiple else "Single",
        "active": is_active,
    })
    return doc_type


def update(db: Session, doc_type: DocumentType, changes: dict, *, user_id: int, admin_username: str) -> DocumentType:
    """Apply only the supplied fields; each kind of change is its own audit event."""
    if "label" in changes and changes["label"] is not None:
        label = changes["label"].strip()
        if label != doc_type.label:
            _assert_label_free(db, label, exclude_id=doc_type.id)
            old = doc_type.label
            doc_type.label = label
            _record(db, admin_username, "DOCUMENT_TYPE_RENAMED", doc_type, {"label": old}, {"label": label})
    if "description" in changes:
        description = (changes["description"] or "").strip() or None
        if description != doc_type.description:
            old = doc_type.description
            doc_type.description = description
            _record(db, admin_username, "DOCUMENT_TYPE_UPDATED", doc_type, {"description": old}, {"description": description})
    if changes.get("is_active") is not None and changes["is_active"] != doc_type.is_active:
        doc_type.is_active = changes["is_active"]
        _record(
            db, admin_username,
            "DOCUMENT_TYPE_ENABLED" if doc_type.is_active else "DOCUMENT_TYPE_DISABLED",
            doc_type, {"active": not doc_type.is_active}, {"active": doc_type.is_active},
        )
    if changes.get("is_required") is not None and changes["is_required"] != doc_type.is_required:
        doc_type.is_required = changes["is_required"]
        before, after = ("Optional", "Required") if doc_type.is_required else ("Required", "Optional")
        _record(db, admin_username, "DOCUMENT_TYPE_REQUIREMENT_CHANGED", doc_type, {"requirement": before}, {"requirement": after})
    if changes.get("allow_multiple") is not None and changes["allow_multiple"] != doc_type.allow_multiple:
        # Applies to uploads from now on. Switching to Single never deletes or
        # hides files schedules already hold; see multi_file_schedule_counts.
        doc_type.allow_multiple = changes["allow_multiple"]
        before, after = ("Single", "Multiple") if doc_type.allow_multiple else ("Multiple", "Single")
        _record(db, admin_username, "DOCUMENT_TYPE_FILE_MODE_CHANGED", doc_type, {"file_mode": before}, {"file_mode": after})
    doc_type.updated_by_user_id = user_id
    db.flush()
    return doc_type


def reorder(db: Session, ordered_ids: list[int], *, user_id: int, admin_username: str) -> list[DocumentType]:
    current = all_types(db)
    if sorted(ordered_ids) != sorted(t.id for t in current) or len(set(ordered_ids)) != len(ordered_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The new order must list every document type exactly once.",
        )
    before = [t.label for t in current]
    by_id = {t.id: t for t in current}
    for position, type_id in enumerate(ordered_ids, start=1):
        by_id[type_id].display_order = position
        by_id[type_id].updated_by_user_id = user_id
    db.flush()
    after = [by_id[i].label for i in ordered_ids]
    if before != after:
        audit_service.record(
            db,
            event_type="DOCUMENT_TYPES_REORDERED",
            actor_type="ADMIN",
            admin_username=admin_username,
            old_values={"order": before},
            new_values={"order": after},
        )
    return all_types(db)


def delete(db: Session, doc_type: DocumentType, *, admin_username: str) -> None:
    """Remove a type created by mistake. Types with uploaded files are disabled instead."""
    used = db.scalar(select(func.count(BookingAttachment.id)).where(BookingAttachment.category == doc_type.key)) or 0
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{doc_type.label}” has {used} uploaded file{'s' if used != 1 else ''}. "
            "Disable it instead so those documents stay available.",
        )
    _record(db, admin_username, "DOCUMENT_TYPE_DELETED", doc_type, {"active": doc_type.is_active}, None)
    db.delete(doc_type)
    db.flush()
