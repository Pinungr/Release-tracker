"""Safe attachment storage.

Rules enforced here:
  * uploads are written under storage/deployments/<booking-id>/<category>/
  * the stored name is a UUID plus a whitelisted extension, so a hostile
    filename can never influence the path
  * the resolved path is re-checked against the storage root (path traversal)
  * nothing is ever marked executable or served with a guessable path
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path

from ..config import settings

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".zip",
    ".sql",
    ".png",
    ".jpg",
    ".jpeg",
}

CATEGORY_FOLDERS = {
    "TEST_RESULTS": "test-results",
    "INVENTORY": "inventory",
    "IMPLEMENTATION_PLAN": "implementation-plan",
    "VALIDATION_PLAN": "validation-plan",
    "DBA_SCRIPT": "dba-script",
    "SUPPORTING_DOCUMENTS": "supporting-documents",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def storage_root() -> Path:
    root = settings.storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(raw: str) -> str:
    """Display-only name: no separators, no control characters, bounded length."""
    name = unicodedata.normalize("NFKD", raw or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip("._") or "upload"
    if len(name) > 120:
        stem, _, ext = name.rpartition(".")
        name = f"{stem[: 110 - len(ext)]}.{ext}" if ext else stem[:120]
    return name


def extension_of(raw: str) -> str:
    return Path(sanitize_filename(raw)).suffix.lower()


def is_allowed_extension(raw: str) -> bool:
    return extension_of(raw) in ALLOWED_EXTENSIONS


def build_stored_name(raw: str) -> str:
    return f"{uuid.uuid4().hex}{extension_of(raw)}"


def attachment_dir(booking_id: int, category: str) -> Path:
    folder = CATEGORY_FOLDERS.get(category)
    if folder is None:
        raise ValueError(f"Unknown document category: {category}")
    target = (storage_root() / str(int(booking_id)) / folder).resolve()
    _assert_inside(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def attachment_path(booking_id: int, category: str, stored_filename: str) -> Path:
    safe = sanitize_filename(stored_filename)
    path = (attachment_dir(booking_id, category) / safe).resolve()
    _assert_inside(path)
    return path


def _assert_inside(path: Path) -> None:
    root = storage_root()
    if root != path and root not in path.parents:
        raise ValueError("Resolved storage path escapes the storage root.")
