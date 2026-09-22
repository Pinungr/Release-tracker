"""Append-only audit trail for every booking / admin mutation."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from ..models import BookingAudit, DeploymentBooking

AUDITED_FIELDS = (
    "tenant_id",
    "tenant_name",
    "created_by_user_id",
    "deployment_date",
    "slot_number",
    "jira_number",
    "jira_url",
    "change_number",
    "work_started_by_user_id",
    "work_started_at",
    "environment",
    "technology",
    "requester_name",
    "requester_email",
    "requester_phone",
    "verifier_name",
    "verifier_email",
    "git_repository",
    "implementation_summary",
    "deployment_description",
    "justification",
    "impacted_region",
    "additional_comments",
    "status",
    "is_emergency",
    "emergency_reason",
    "emergency_approval_reference",
    "emergency_approver",
    "business_justification",
)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def snapshot(booking: DeploymentBooking) -> dict[str, Any]:
    return {f: getattr(booking, f) for f in AUDITED_FIELDS}


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for key, new_value in after.items():
        if before.get(key) != new_value:
            old[key] = before.get(key)
            new[key] = new_value
    return old, new


def record(
    db: Session,
    *,
    event_type: str,
    booking: DeploymentBooking | None = None,
    actor_type: str = "SYSTEM",
    requester_email: str | None = None,
    admin_username: str | None = None,
    override_reason: str | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> BookingAudit:
    event = BookingAudit(
        booking_id=booking.id if booking else None,
        booking_reference=booking.booking_reference if booking else None,
        event_type=event_type,
        actor_type=actor_type,
        requester_email=requester_email,
        admin_username=admin_username,
        override_reason=override_reason,
        old_values=json.dumps(old_values, default=_json_default) if old_values else None,
        new_values=json.dumps(new_values, default=_json_default) if new_values else None,
    )
    db.add(event)
    return event
