"""Microsoft Teams Workflows booking notifications: configuration, safety and delivery."""
from __future__ import annotations

import asyncio
import httpx
import pytest

from app.models import ApplicationSetting, BookingAudit
from app.services import teams_notification_service as teams
from conftest import booking_payload, create_booking, post_booking, promote_to_release_manager, sign_up_and_login

VALID_URL = (
    "https://example.ae.environment.api.powerplatform.com:443/powerautomate/automations/direct/"
    "workflows/abc/triggers/manual/paths/invoke?api-version=1&sig=secret-token"
)
OTHER_URL = "https://two.ae.environment.api.powerplatform.com/powerautomate/automations/direct/workflows/def?sig=secret-two"
SETTINGS = "/api/admin/notifications/teams"


@pytest.fixture
def sent(monkeypatch):
    """Capture deliveries instead of calling Teams, noting whether they ran on the event loop."""
    calls: list[dict] = []

    def fake_post(url, payload):
        try:
            asyncio.get_running_loop()
            on_event_loop = True
        except RuntimeError:
            on_event_loop = False
        calls.append({"url": url, "payload": payload, "on_event_loop": on_event_loop})

    monkeypatch.setattr(teams, "_post", fake_post)
    return calls


def _enable(admin, url=VALID_URL):
    response = admin.put(SETTINGS, json={"webhook_url": url, "enabled": True})
    assert response.status_code == 200, response.text


def _card(call) -> dict:
    payload = call["payload"]
    assert payload["type"] == "message"
    attachment = payload["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    return attachment["content"]


def _facts(call) -> dict[str, str]:
    fact_set = next(block for block in _card(call)["body"] if block["type"] == "FactSet")
    return {fact["title"]: fact["value"] for fact in fact_set["facts"]}


def _group_id(admin, group_type):
    return next(g["id"] for g in admin.get("/api/admin/groups").json() if g["group_type"] == group_type)


# --------------------------------------------------------------------------- #
# Webhook validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [
    "https://",                                                         # no host
    "https://10.0.0.5/internal",                                        # internal address
    "https://evil.example/hook",                                        # arbitrary host
    "http://example.ae.environment.api.powerplatform.com/hook",         # not HTTPS
    "https://example.ae.environment.api.powerplatform.com:444/hook",    # unexpected port
    "https://example.ae.environment.api.powerplatform.com/",            # no trigger path
    "https://api.powerplatform.com.evil.example/hook",                  # lookalike host
    "https://evil.example/x.api.powerplatform.com",                     # allowed name only in the path
    "https://user:pass@example.ae.environment.api.powerplatform.com/x", # embedded credentials
    "https://contoso.webhook.office.com/webhookb2/x",                   # retired Office 365 connector
    "https://prod-12.westus.logic.azure.com:443/workflows/abc",         # old Workflows host
])
def test_only_teams_workflows_urls_are_accepted(admin, url):
    with pytest.raises(ValueError):
        teams.validate_webhook_url(url)
    assert admin.put(SETTINGS, json={"webhook_url": url, "enabled": True}).status_code == 422
    assert admin.get(SETTINGS).json()["webhook_configured"] is False


def test_a_workflows_url_is_accepted():
    assert teams.validate_webhook_url(VALID_URL) == VALID_URL


# --------------------------------------------------------------------------- #
# Who can configure
# --------------------------------------------------------------------------- #


def test_tenant_users_and_management_have_no_access(anon, admin, user):
    manager = sign_up_and_login(anon, "manager")
    admin.post(f"/api/admin/groups/{_group_id(admin, 'MANAGEMENT')}/members/{manager.get('/api/auth/me').json()['id']}")
    for client in (user, manager):
        assert client.get(SETTINGS).status_code == 403
        assert client.put(SETTINGS, json={"enabled": False}).status_code == 403
        assert client.post(f"{SETTINGS}/test").status_code == 403


def test_release_managers_can_view_but_only_the_owner_changes_or_tests(admin, user):
    promote_to_release_manager(admin, user)
    assert user.get(SETTINGS).status_code == 200
    assert user.put(SETTINGS, json={"webhook_url": VALID_URL, "enabled": True}).status_code == 403
    assert user.put(SETTINGS, json={"clear_webhook": True}).status_code == 403
    assert user.post(f"{SETTINGS}/test").status_code == 403


# --------------------------------------------------------------------------- #
# Settings, secrecy and audit
# --------------------------------------------------------------------------- #


def test_webhook_is_never_returned_or_audited(admin):
    _enable(admin)
    assert admin.get(SETTINGS).json() == {"enabled": True, "webhook_configured": True, "webhook_valid": True}
    assert "secret" not in admin.get(SETTINGS).text
    events = [e for e in admin.get("/api/admin/audit").json() if e["event_type"] == "TEAMS_NOTIFICATION_SETTINGS_UPDATED"]
    assert events and all("secret" not in str(e) and "powerplatform" not in str(e) for e in events)


def test_add_replace_and_remove_are_distinguishable_in_audit(admin, db):
    assert admin.put(SETTINGS, json={"webhook_url": VALID_URL}).status_code == 200
    assert admin.put(SETTINGS, json={"webhook_url": OTHER_URL}).status_code == 200
    assert admin.put(SETTINGS, json={"clear_webhook": True}).status_code == 200
    events = [e for e in admin.get("/api/admin/audit").json() if e["event_type"] == "TEAMS_NOTIFICATION_SETTINGS_UPDATED"]
    removed, replaced, added = (e["new_values"] for e in events[:3])  # newest first
    assert added["webhook_added"] is True and added["webhook_replaced"] is False
    assert replaced["webhook_replaced"] is True and replaced["webhook_added"] is False
    assert removed["webhook_removed"] is True
    stored = [row.new_values or "" for row in db.query(BookingAudit).filter(BookingAudit.event_type == "TEAMS_NOTIFICATION_SETTINGS_UPDATED")]
    assert all(VALID_URL not in value and OTHER_URL not in value for value in stored)


def test_enabling_requires_a_webhook_and_removing_it_disables(admin):
    assert admin.put(SETTINGS, json={"enabled": True}).status_code == 422
    _enable(admin)
    assert admin.put(SETTINGS, json={"clear_webhook": True}).json() == {
        "enabled": False, "webhook_configured": False, "webhook_valid": False,
    }


def test_an_old_saved_connector_url_is_reported_never_called_and_cannot_be_enabled(admin, user, tenant, next_monday, sent, db):
    db.add(ApplicationSetting(key=teams.WEBHOOK_KEY, value="https://contoso.webhook.office.com/webhookb2/old"))
    db.add(ApplicationSetting(key=teams.ENABLED_KEY, value="true"))
    db.commit()
    assert admin.get(SETTINGS).json() == {"enabled": True, "webhook_configured": True, "webhook_valid": False}
    create_booking(user, tenant, next_monday, 1)
    assert sent == []
    assert admin.post(f"{SETTINGS}/test").status_code == 422
    admin.put(SETTINGS, json={"enabled": False})
    assert admin.put(SETTINGS, json={"enabled": True}).status_code == 422
    # Replacing it with a Workflows URL fixes it.
    _enable(admin)
    assert admin.get(SETTINGS).json()["webhook_valid"] is True


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def test_booking_notification_is_an_adaptive_card_sent_off_the_event_loop(admin, user, tenant, next_monday, sent):
    _enable(admin)
    booking = create_booking(user, tenant, next_monday, 1)
    assert len(sent) == 1
    assert sent[0]["url"] == VALID_URL
    # A blocking HTTP call on the event loop would stall every other request on
    # the single worker; background delivery runs in a worker thread instead.
    assert sent[0]["on_event_loop"] is False
    facts = _facts(sent[0])
    # Dates and schedule numbers arrive exactly as written, without escapes.
    assert facts["Schedule"] == booking["booking_reference"]
    assert facts["Deployment date"] == next_monday.isoformat()
    assert facts["Slot"] == "Slot 1"


def test_notification_contains_no_requester_or_free_form_summary(admin, user, tenant, next_monday, sent):
    _enable(admin)
    create_booking(user, tenant, next_monday, 1, implementation_summary="confidential rollout details")
    text = str(sent[0]["payload"])
    assert "Pinaki" not in text and "pinaki@example.com" not in text
    assert "confidential rollout details" not in text


def test_no_notification_when_disabled(admin, user, tenant, next_monday, sent):
    create_booking(user, tenant, next_monday, 1)
    _enable(admin)
    admin.put(SETTINGS, json={"enabled": False})
    create_booking(user, tenant, next_monday, 2)
    assert sent == []


def test_booking_succeeds_when_teams_is_down(admin, user, tenant, next_monday, monkeypatch):
    _enable(admin)

    def down(url, payload):
        raise httpx.ConnectError("Teams unreachable")

    monkeypatch.setattr(teams, "_post", down)
    assert post_booking(user, booking_payload(tenant, next_monday, 1)).status_code == 201


def test_background_sender_never_raises(monkeypatch):
    def broken_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(teams, "SessionLocal", broken_session)
    assert teams.notify_booking_created_background(123) is None


def test_background_worker_opens_its_own_session(admin, user, tenant, next_monday, sent):
    booking = create_booking(user, tenant, next_monday, 1)
    _enable(admin)
    teams.notify_booking_created_background(booking["id"])
    assert _facts(sent[0])["Schedule"] == booking["booking_reference"]


def test_test_notification_reports_teams_failures(admin, monkeypatch, sent):
    _enable(admin)
    assert admin.post(f"{SETTINGS}/test").status_code == 204
    assert _card(sent[0])["body"][0]["text"] == "PDS Teams notification test"

    def rejected(url, payload):
        raise httpx.HTTPStatusError("400", request=httpx.Request("POST", url), response=httpx.Response(400))

    monkeypatch.setattr(teams, "_post", rejected)
    assert admin.post(f"{SETTINGS}/test").status_code == 502


# --------------------------------------------------------------------------- #
# Card text
# --------------------------------------------------------------------------- #


def test_card_text_cannot_render_as_a_disguised_link():
    card = teams._adaptive_card("PDS **title**", [("Summary", "**[click](https://evil.example)**")])["attachments"][0]["content"]
    assert card["body"][0]["text"] == r"PDS \*\*title\*\*"
    assert card["body"][1]["facts"][0]["value"] == r"\*\*\[click\]\(https://evil.example\)\*\*"
    assert "MessageCard" not in str(card)


def test_plain_text_keeps_dates_numbers_and_sentences_readable():
    for value in ("2026-10-20", "pds-001", "Open PDS for deployment details and documents."):
        assert teams._plain(value) == value


def test_post_does_not_follow_redirects(monkeypatch):
    """An allowed Microsoft URL must not be able to redirect PDS to another host."""
    created: list[dict] = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json):
            return httpx.Response(202, request=httpx.Request("POST", url))

    monkeypatch.setattr(teams.httpx, "Client", FakeClient)
    teams._post(VALID_URL, {"type": "message"})
    assert created[0]["follow_redirects"] is False
