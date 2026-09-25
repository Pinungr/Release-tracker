"""Reuse existing schedule images without copying bytes or widening access."""
import json
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..models import BookingAudit, DeploymentBooking
from ..utils import files as file_utils
from .comment_attachment_service import attachment_path


class ImageReference(BaseModel):
    kind: Literal['document', 'comment']
    attachment_id: str = Field(min_length=1, max_length=128)
    comment_id: int | None = Field(default=None, ge=1)


class ReferencedImage(ImageReference):
    original_filename: str
    internal: bool = False


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in {'.png', '.jpg', '.jpeg'}


def resolve_image(db: Session, booking: DeploymentBooking, ref: ImageReference, *, allow_internal: bool):
    internal = False
    if ref.kind == 'document':
        attachment = next((a for a in booking.attachments if str(a.id) == ref.attachment_id), None)
        if attachment is None or ref.comment_id is not None:
            raise HTTPException(404, 'Image not found on this schedule.')
        filename = attachment.original_filename
        path = file_utils.attachment_path(booking.id, attachment.category, attachment.stored_filename)
    else:
        event = db.get(BookingAudit, ref.comment_id) if ref.comment_id else None
        if event is None or event.booking_id != booking.id or event.event_type not in {'COMMENT_ADDED', 'INTERNAL_NOTE_ADDED'}:
            raise HTTPException(404, 'Image not found on this schedule.')
        internal = event.event_type == 'INTERNAL_NOTE_ADDED'
        if internal and not allow_internal:
            raise HTTPException(403, 'Internal RM images cannot be used in public comments.')
        attachment = next((a for a in json.loads(event.new_values or '{}').get('attachments', []) if a['id'] == ref.attachment_id), None)
        if attachment is None:
            raise HTTPException(404, 'Image not found on this schedule.')
        filename = attachment['original_filename']
        path = attachment_path(booking.id, event.id, attachment['id'])
    if not is_image(filename):
        raise HTTPException(422, 'Select a PNG or JPEG image.')
    if not path.is_file():
        raise HTTPException(410, 'This image is no longer available. Remove it and select another.')
    return ReferencedImage(**ref.model_dump(), original_filename=filename, internal=internal), path


def validated_images(db: Session, booking: DeploymentBooking, refs: list[ImageReference], *, allow_internal: bool):
    images = []
    seen = set()
    for ref in refs:
        key = (ref.kind, ref.comment_id, ref.attachment_id)
        if key not in seen:
            image, _ = resolve_image(db, booking, ref, allow_internal=allow_internal)
            images.append(image.model_dump())
            seen.add(key)
    return images
