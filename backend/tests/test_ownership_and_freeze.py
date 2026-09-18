"""Ownership verification, the configurable freeze window and My Bookings."""
from __future__ import annotations

from conftest import booking_payload

OWNER = {"requester_email": "rahul.menon@example.com", "booking_pin": "123456"}


def _update_payload(day, slot, **overrides) -> dict:
    payload = booking_payload(day, slot)
    for key in ("booking_pin", "confirm_booking_pin"):
        payload.pop(key)
    payload.update(overrides)
    return payload


def _set_freeze_hours(client, admin_headers, hours: int) -> None:
    response = client.put(
        "/api/admin/settings", json={"booking_freeze_hours": hours}, headers=admin_headers
    )
    assert response.status_code == 200, response.text


def test_correct_pin_allows_edit(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    response = client.put(
        f"/api/bookings/{booking_id}",
        json=_update_payload(next_monday, 1, jira_change="CHG0999999", credentials=OWNER),
    )
    assert response.status_code == 200, response.text
    assert response.json()["jira_change"] == "CHG0999999"


def test_wrong_pin_blocks_edit(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    response = client.put(
        f"/api/bookings/{created['booking']['id']}",
        json=_update_payload(
            next_monday,
            1,
            credentials={"requester_email": "rahul.menon@example.com", "booking_pin": "000000"},
        ),
    )
    assert response.status_code == 403
    assert "Incorrect" in response.json()["detail"]


def test_cannot_edit_someone_elses_booking(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    response = client.put(
        f"/api/bookings/{created['booking']['id']}",
        json=_update_payload(
            next_monday,
            1,
            credentials={"requester_email": "someone.else@example.com", "booking_pin": "123456"},
        ),
    )
    assert response.status_code == 403


def test_missing_credentials_are_rejected(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    response = client.put(
        f"/api/bookings/{created['booking']['id']}", json=_update_payload(next_monday, 1)
    )
    assert response.status_code == 401


def test_verify_owner_returns_a_manage_token(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    response = client.post(f"/api/bookings/{booking_id}/verify-owner", json=OWNER)
    assert response.status_code == 200
    token = response.json()["manage_token"]
    assert response.json()["booking"]["requester_email"] == "rahul.menon@example.com"

    by_token = client.get(f"/api/bookings/manage/token/{token}")
    assert by_token.status_code == 200
    assert by_token.json()["id"] == booking_id


def test_stale_manage_token_stops_working(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    old_token = created["manage_token"]
    client.post(f"/api/bookings/{created['booking']['id']}/verify-owner", json=OWNER)
    assert client.get(f"/api/bookings/manage/token/{old_token}").status_code == 404


def test_public_edit_blocked_inside_the_freeze_window(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    _set_freeze_hours(client, admin_headers, 720)  # 30 days: the booking is now frozen

    response = client.put(
        f"/api/bookings/{booking_id}", json=_update_payload(next_monday, 1, credentials=OWNER)
    )
    assert response.status_code == 423
    assert "Changes are disabled within 720 hours" in response.json()["detail"]

    cancel = client.request(
        "DELETE", f"/api/bookings/{booking_id}", json={"credentials": OWNER}
    )
    assert cancel.status_code == 423


def test_admin_can_edit_inside_the_freeze_window(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    _set_freeze_hours(client, admin_headers, 720)

    response = client.put(
        f"/api/bookings/{booking_id}",
        json=_update_payload(
            next_monday,
            1,
            jira_change="CHG0777777",
            override_reason="Critical business deployment.",
        ),
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["jira_change"] == "CHG0777777"

    audit = client.get(f"/api/admin/audit?booking_id={booking_id}", headers=admin_headers).json()
    assert any(e["override_reason"] == "Critical business deployment." for e in audit)


def test_admin_edit_inside_freeze_requires_a_reason(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    _set_freeze_hours(client, admin_headers, 720)
    response = client.put(
        f"/api/bookings/{created['booking']['id']}",
        json=_update_payload(next_monday, 1, jira_change="CHG0777777"),
        headers=admin_headers,
    )
    assert response.status_code == 400


def test_booking_reports_its_lock_state(client, admin_headers, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    slot = schedule["days"][0]["slots"][0]
    assert slot["state"] == "BOOKED"
    assert slot["booking"]["is_locked"] is False

    _set_freeze_hours(client, admin_headers, 720)
    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert schedule["days"][0]["slots"][0]["booking"]["is_locked"] is True


def test_my_bookings_requires_the_right_pin(client, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    ok = client.post("/api/my-bookings", json=OWNER)
    assert ok.status_code == 200
    assert len(ok.json()) == 1
    assert ok.json()[0]["requester_email"] == "rahul.menon@example.com"

    wrong = client.post(
        "/api/my-bookings",
        json={"requester_email": "rahul.menon@example.com", "booking_pin": "999999"},
    )
    assert wrong.status_code == 200
    assert wrong.json() == []


def test_owner_verification_is_rate_limited(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    statuses = [
        client.post(
            f"/api/bookings/{booking_id}/verify-owner",
            json={"requester_email": "rahul.menon@example.com", "booking_pin": "000000"},
        ).status_code
        for _ in range(12)
    ]
    assert 429 in statuses


def test_cancelled_booking_cannot_be_edited(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    client.request("DELETE", f"/api/bookings/{booking_id}", json={"credentials": OWNER})
    response = client.put(
        f"/api/bookings/{booking_id}", json=_update_payload(next_monday, 1, credentials=OWNER)
    )
    assert response.status_code == 400
    assert "cancelled" in response.json()["detail"]
