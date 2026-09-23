"""Typed access to the ApplicationSetting key/value table."""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApplicationSetting, DocumentCategory

DEFAULTS: dict[str, object] = {
    "regular_slots_per_day": 4,
    "weekly_booking_limit": 2,
    "booking_freeze_dates": 2,
    "jira_required_at_booking": False,
    "max_file_size_mb": 20,
    "mandatory_documents": [
        DocumentCategory.TEST_RESULTS.value,
        DocumentCategory.INVENTORY.value,
        DocumentCategory.IMPLEMENTATION_PLAN.value,
        DocumentCategory.VALIDATION_PLAN.value,
        DocumentCategory.DBA_SCRIPT.value,
    ],
}

INT_KEYS = {"regular_slots_per_day", "weekly_booking_limit", "booking_freeze_dates", "max_file_size_mb"}
BOOL_KEYS = {"jira_required_at_booking"}
LIST_KEYS = {"mandatory_documents"}

LIMITS = {
    "regular_slots_per_day": (1, 12),
    "weekly_booking_limit": (1, 25),
    "booking_freeze_dates": (0, 25),
    "max_file_size_mb": (1, 200),
}


@dataclass(frozen=True)
class AppSettings:
    regular_slots_per_day: int
    weekly_booking_limit: int
    booking_freeze_dates: int
    jira_required_at_booking: bool
    max_file_size_mb: int
    mandatory_documents: list[str]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def _decode(key: str, raw: str) -> object:
    if key in INT_KEYS:
        return int(raw)
    if key in BOOL_KEYS:
        return raw.lower() in {"1", "true", "yes"}
    if key in LIST_KEYS:
        return json.loads(raw)
    return raw


def _encode(key: str, value: object) -> str:
    if key in BOOL_KEYS:
        return "true" if value else "false"
    if key in LIST_KEYS:
        return json.dumps(list(value))  # type: ignore[arg-type]
    return str(value)


def get_settings_dict(db: Session) -> dict[str, object]:
    values = dict(DEFAULTS)
    for row in db.scalars(select(ApplicationSetting)).all():
        if row.key in values:
            try:
                values[row.key] = _decode(row.key, row.value)
            except (ValueError, json.JSONDecodeError):
                continue
    return values


def get_app_settings(db: Session) -> AppSettings:
    values = get_settings_dict(db)
    return AppSettings(**values)  # type: ignore[arg-type]


def update_settings(db: Session, changes: dict[str, object]) -> AppSettings:
    for key, value in changes.items():
        if value is None or key not in DEFAULTS:
            continue
        if key in LIMITS:
            low, high = LIMITS[key]
            value = max(low, min(high, int(value)))
        if key == "mandatory_documents":
            valid = {c.value for c in DocumentCategory}
            value = [v for v in value if v in valid]  # type: ignore[union-attr]
        row = db.get(ApplicationSetting, key)
        if row is None:
            db.add(ApplicationSetting(key=key, value=_encode(key, value)))
        else:
            row.value = _encode(key, value)
    db.flush()
    return get_app_settings(db)
