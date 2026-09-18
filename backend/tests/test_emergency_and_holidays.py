"""Emergency slot access, holidays and per-day slot overrides."""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload, emergency_payload


def test_public_user_cannot_book_the_emergency_slot(client, next_monday):
    response = client.post("/api/bookings", json=emergency_payload(next_monday))
    assert response.status_code == 403
    assert "administrator" in response.json()["detail"]


def test_admin_can_book_the_emergency_slot(client, admin_headers, next_monday):
    response = client.post(
        "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["booking"]["is_emergency"] is True
    assert response.json()["booking"]["emergency_reason"]


def test_emergency_booking_requires_reason_and_justification(client, admin_headers, next_monday):
    payload = emergency_payload(next_monday)
    payload["emergency_reason"] = ""
    response = client.post("/api/bookings", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "Emergency Reason is required" in response.json()["detail"]

    payload = emergency_payload(next_monday)
    payload["business_justification"] = "   "
    response = client.post("/api/bookings", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "Business Justification is required" in response.json()["detail"]


def test_emergency_booking_does_not_consume_the_weekly_limit(client, admin_headers, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    client.post("/api/bookings", json=booking_payload(next_monday, 2))
    emergency = client.post(
        "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
    )
    assert emergency.status_code == 201, emergency.text


def test_emergency_slot_is_visible_but_locked_to_the_public(client, next_monday):
    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    slot5 = schedule["days"][0]["slots"][4]
    assert slot5["is_emergency"] is True
    assert slot5["state"] == "EMERGENCY_AVAILABLE"
    assert slot5["bookable_by_public"] is False
    assert slot5["bookable_by_admin"] is True


def test_public_cannot_edit_an_emergency_booking(client, admin_headers, next_monday):
    created = client.post(
        "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
    ).json()
    payload = booking_payload(next_monday, 5)
    payload.pop("booking_pin")
    payload.pop("confirm_booking_pin")
    payload["credentials"] = {
        "requester_email": "rahul.menon@example.com",
        "booking_pin": "123456",
    }
    response = client.put(f"/api/bookings/{created['booking']['id']}", json=payload)
    assert response.status_code == 403


def test_admin_creates_a_holiday_and_it_blocks_bookings(client, admin_headers, next_monday):
    created = client.post(
        "/api/admin/holidays",
        json={
            "holiday_date": next_monday.isoformat(),
            "name": "Indian Public Holiday",
            "description": "No production deployments available.",
            "is_full_day": True,
            "allow_emergency": True,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text

    blocked = client.post("/api/bookings", json=booking_payload(next_monday, 1))
    assert blocked.status_code == 400
    assert "no production deployments available" in blocked.json()["detail"].lower()

    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday = schedule["days"][0]
    assert monday["holiday"]["name"] == "Indian Public Holiday"
    assert monday["regular_slots_total"] == 0
    assert all(s["state"] == "HOLIDAY" for s in monday["slots"] if not s["is_emergency"])
    assert schedule["summary"]["holidays"] == 1


def test_emergency_stays_open_on_a_holiday_when_allowed(client, admin_headers, next_monday):
    client.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Festival", "allow_emergency": True},
        headers=admin_headers,
    )
    response = client.post(
        "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
    )
    assert response.status_code == 201, response.text


def test_emergency_blocked_on_a_holiday_when_disallowed(client, admin_headers, next_monday):
    client.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Festival", "allow_emergency": False},
        headers=admin_headers,
    )
    response = client.post(
        "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
    )
    assert response.status_code == 400
    assert "not permitted on this holiday" in response.json()["detail"]


def test_partial_holiday_keeps_regular_slots_open(client, admin_headers, next_monday):
    client.post(
        "/api/admin/holidays",
        json={
            "holiday_date": next_monday.isoformat(),
            "name": "Half day",
            "is_full_day": False,
        },
        headers=admin_headers,
    )
    assert client.post("/api/bookings", json=booking_payload(next_monday, 1)).status_code == 201


def test_holiday_update_and_delete(client, admin_headers, next_monday):
    created = client.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Placeholder"},
        headers=admin_headers,
    ).json()
    updated = client.put(
        f"/api/admin/holidays/{created['id']}",
        json={"holiday_date": next_monday.isoformat(), "name": "Renamed", "is_full_day": True},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"

    assert (
        client.delete(f"/api/admin/holidays/{created['id']}", headers=admin_headers).status_code == 204
    )
    assert client.get("/api/admin/holidays", headers=admin_headers).json() == []


def test_duplicate_holiday_is_rejected(client, admin_headers, next_monday):
    body = {"holiday_date": next_monday.isoformat(), "name": "Holiday"}
    assert client.post("/api/admin/holidays", json=body, headers=admin_headers).status_code == 201
    assert client.post("/api/admin/holidays", json=body, headers=admin_headers).status_code == 409


def test_holiday_management_requires_admin(client, next_monday):
    response = client.post(
        "/api/admin/holidays", json={"holiday_date": next_monday.isoformat(), "name": "Nope"}
    )
    assert response.status_code == 401


def test_daily_override_reduces_the_slots_for_one_date(client, admin_headers, next_monday):
    tuesday = next_monday + timedelta(days=1)
    response = client.put(
        "/api/admin/overrides",
        json={
            "override_date": tuesday.isoformat(),
            "regular_slots": 2,
            "emergency_enabled": False,
            "note": "Change freeze window",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200

    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert schedule["days"][0]["regular_slots_total"] == 4  # Monday untouched
    assert schedule["days"][1]["regular_slots_total"] == 2
    assert schedule["days"][1]["slots"][4]["state"] == "DISABLED"

    assert client.post("/api/bookings", json=booking_payload(tuesday, 3)).status_code == 400
    assert (
        client.post("/api/bookings", json=emergency_payload(tuesday), headers=admin_headers).status_code
        == 400
    )
