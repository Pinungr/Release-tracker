"""Comment files are separate from required deployment documents."""
from pathlib import Path
from fastapi import HTTPException, UploadFile
from ..utils import files as file_utils

MAX_BYTES = 20 * 1024 * 1024


def attachment_path(booking_id: int, comment_id: int, stored_name: str) -> Path:
    root = file_utils.storage_root()
    path = (root / str(int(booking_id)) / "comments" / str(int(comment_id)) / file_utils.sanitize_filename(stored_name)).resolve()
    if root not in path.parents:
        raise HTTPException(400, "Invalid attachment path.")
    return path


def save_files(booking_id: int, comment_id: int, uploads: list[UploadFile], written_paths: list[Path]) -> list[dict]:
    result = []
    for upload in uploads:
        raw_name = upload.filename or ""
        if not raw_name.strip() or not file_utils.is_allowed_extension(raw_name):
            raise HTTPException(422, "Unsupported comment attachment. Allowed: " + ", ".join(sorted(file_utils.ALLOWED_EXTENSIONS)))
        stored = file_utils.build_stored_name(raw_name)
        path = attachment_path(booking_id, comment_id, stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        written_paths.append(path)
        size = 0
        with path.open("wb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Each comment attachment must be 20 MB or smaller.")
                target.write(chunk)
        if size == 0:
            raise HTTPException(422, "Empty comment attachments are not allowed.")
        result.append({"id": stored, "original_filename": file_utils.sanitize_filename(raw_name), "size_bytes": size})
    return result
