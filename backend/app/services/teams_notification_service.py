"""Microsoft Teams Workflows notifications configured from Release Controls.

The webhook secret stays in ApplicationSetting and is never returned by an API.
Booking delivery is best-effort and runs after the response in a FastAPI background
thread with a fresh SQLAlchemy session, so a slow Teams endpoint cannot block PDS.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ApplicationSetting, DeploymentBooking

log = logging.getLogger(__name__)

ENABLED_KEY = "teams_notifications_enabled"
WEBHOOK_KEY = "teams_webhook_url"

# Teams Workflows / Power Automate trigger URLs moved to Power Platform hosts.
# Deliberately do not permit arbitrary HTTPS destinations (SSRF/data-exfiltration guard).
_ALLOWED_HOST_SUFFIXES = (".api.powerplatform.com", ".environment.api.powerplatform.com")
# Only characters that create links, emphasis, code or HTML are escaped. Dates,
# schedule numbers and sentences ('-', '.') stay as they are, so Teams never
# shows stray backslashes such as "2026\-10\-20".
_MARKDOWN = re.compile(r"([\\`*_\[\]()<>#])")


def _row(db: Session, key: str) -> ApplicationSetting | None:
    return db.get(ApplicationSetting, key)


def enabled(db: Session) -> bool:
    row = _row(db, ENABLED_KEY)
    return bool(row and row.value.strip().lower() in {"1", "true", "yes", "on"})


def webhook_url(db: Session) -> str:
    row = _row(db, WEBHOOK_KEY)
    return row.value.strip() if row else ""


def webhook_is_valid(url: str) -> bool:
    try:
        validate_webhook_url(url)
    except ValueError:
        return False
    return True


def settings_out(db: Session) -> dict[str, object]:
    url = webhook_url(db)
    # A webhook saved before Workflows-only validation (e.g. an old Office 365
    # connector) is never called; report it so the UI can ask for a new one
    # instead of showing "configured" while nothing is delivered.
    return {
        "enabled": enabled(db),
        "webhook_configured": bool(url),
        "webhook_valid": bool(url) and webhook_is_valid(url),
    }


def validate_webhook_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid Microsoft Teams Workflows webhook URL.") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Enter a valid HTTPS Microsoft Teams Workflows webhook URL.")
    if port not in (None, 443):
        raise ValueError("Teams Workflows webhook URLs must use HTTPS port 443.")
    if not any(host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES):
        raise ValueError("Only Microsoft Teams Workflows / Power Automate webhook URLs are allowed.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("The Teams Workflows webhook URL is incomplete.")
    return value


def update_settings(db: Session, *, notifications_enabled: bool | None = None, webhook: str | None = None, clear_webhook: bool = False) -> dict[str, object]:
    if webhook is not None and webhook.strip():
        webhook = validate_webhook_url(webhook)
        row = _row(db, WEBHOOK_KEY)
        if row is None:
            db.add(ApplicationSetting(key=WEBHOOK_KEY, value=webhook))
        else:
            row.value = webhook
    if clear_webhook:
        row = _row(db, WEBHOOK_KEY)
        if row is not None:
            db.delete(row)
        notifications_enabled = False
    if notifications_enabled is not None:
        if notifications_enabled and not ((webhook and webhook.strip()) or webhook_is_valid(webhook_url(db))):
            raise ValueError("Configure a Teams Workflows webhook before enabling notifications.")
        row = _row(db, ENABLED_KEY)
        value = "true" if notifications_enabled else "false"
        if row is None:
            db.add(ApplicationSetting(key=ENABLED_KEY, value=value))
        else:
            row.value = value
    db.flush()
    return settings_out(db)


def _post(url: str, payload: dict[str, object]) -> None:
    # Redirects stay disabled: an allowed Microsoft URL cannot redirect PDS to an
    # arbitrary/private destination. The timeout is isolated to a background thread.
    with httpx.Client(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()


def _plain(value: object) -> str:
    """Escape Adaptive Card markdown so application/user values render as text."""
    return _MARKDOWN.sub(r"\\\1", str(value or ""))


def _adaptive_card(title: str, facts: list[tuple[str, str]], note: str | None = None) -> dict[str, object]:
    body: list[dict[str, object]] = [
        {"type": "TextBlock", "text": _plain(title), "weight": "Bolder", "size": "Medium", "wrap": True},
        {
            "type": "FactSet",
            "facts": [{"title": _plain(name), "value": _plain(value)} for name, value in facts],
        },
    ]
    if note:
        body.append({"type": "TextBlock", "text": _plain(note), "wrap": True, "isSubtle": True})
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": None,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.2",
                "body": body,
            },
        }],
    }


def send_test(db: Session) -> None:
    url = webhook_url(db)
    if not url:
        raise ValueError("Configure a Teams webhook before sending a test notification.")
    # Revalidate old persisted values as well as newly-entered ones.
    url = validate_webhook_url(url)
    _post(url, _adaptive_card(
        "PDS Teams notification test",
        [("Status", "Connected"), ("Source", "Release Controls")],
        "Microsoft Teams notifications are configured successfully.",
    ))


def notify_booking_created(db: Session, booking: DeploymentBooking) -> bool:
    """Synchronous worker body. Call from BackgroundTasks, never the request path."""
    if not enabled(db):
        return False
    url = webhook_url(db)
    if not url:
        log.warning("Teams notifications are enabled but no webhook is configured")
        return False
    try:
        url = validate_webhook_url(url)
    except ValueError as exc:
        # Expected for a webhook saved before Workflows-only validation; the
        # Notifications tab reports it, so a warning (not a traceback) is enough.
        log.warning("Stored Teams webhook is not accepted (%s); booking %s was not notified", exc, booking.booking_reference)
        return False
    slot = "Emergency queue" if booking.is_emergency else f"Slot {booking.slot_number}"
    # Keep channel data deliberately operational/minimal: no requester PII and no
    # free-form implementation summary. Details remain inside authenticated PDS.
    payload = _adaptive_card(
        "New PDS deployment scheduled",
        [
            ("Schedule", booking.booking_reference),
            ("Tenant", booking.tenant_name),
            ("Deployment date", booking.deployment_date.isoformat()),
            ("Slot", slot),
            ("Technology", booking.technology),
            ("Status", booking.status),
        ],
        "Open PDS for deployment details and documents.",
    )
    try:
        _post(url, payload)
        return True
    except Exception:
        log.exception("Teams notification failed for booking %s", booking.booking_reference)
        return False


def notify_booking_created_background(booking_id: int) -> None:
    """Background entry point with its own DB session after the booking commit.

    Never raises: the booking response has already been sent, so any failure
    here (including the database lookup) is logged and otherwise ignored.
    """
    try:
        with SessionLocal() as db:
            booking = db.get(DeploymentBooking, booking_id)
            if booking is None:
                log.warning("Teams notification skipped: booking id %s no longer exists", booking_id)
                return
            notify_booking_created(db, booking)
    except Exception:
        log.exception("Teams notification failed for booking id %s", booking_id)
