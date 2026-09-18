"""Core booking rules: creation, double booking, weekly limit, ownership."""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload


def test_public_booking_succeeds_without_login(client, next_monday):
    response = client.post("/api/bookings", json=booking_payload(next_monday, 2))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["booking"]["booking_reference"].startswith("PDS-")
    assert body["booking"]["status"] == "BOOKED"
    assert body["booking"]["is_emergency"] is False
    assert body["manage_token"]
    assert "Keep your Booking PIN safe" in body["message"] or "keep your Booking PIN safe" in body["message"]


def test_booking_reference_is_sequential_per_day(client, next_monday):
    first = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    second = client.post(
        "/api/bookings", json=booking_payload(next_monday, 2, tenant_name="Encounters")
    ).json()
    day = next_monday.strftime("%Y%m%d")
    assert first["booking"]["booking_reference"] == f"PDS-{day}-001"
    assert second["booking"]["booking_reference"] == f"PDS-{day}-002"


def test_cannot_double_book_the_same_slot(client, next_monday):
    assert client.post("/api/bookings", json=booking_payload(next_monday, 3)).status_code == 201
    clash = client.post(
        "/api/bookings", json=booking_payload(next_monday, 3, tenant_name="Encounters")
    )
    assert clash.status_code == 409
    assert "just been booked" in clash.json()["detail"]


def test_cancelled_slot_becomes_bookable_again(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 3)).json()
    booking_id = created["booking"]["id"]
    cancel = client.request(
        "DELETE",
        f"/api/bookings/{booking_id}",
        json={"credentials": {"requester_email": "rahul.menon@example.com", "booking_pin": "123456"}},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"
    again = client.post("/api/bookings", json=booking_payload(next_monday, 3, tenant_name="Encounters"))
    assert again.status_code == 201


def test_weekly_tenant_limit_blocks_the_third_booking(client, next_monday):
    assert client.post("/api/bookings", json=booking_payload(next_monday, 1)).status_code == 201
    assert client.post("/api/bookings", json=booking_payload(next_monday, 2)).status_code == 201
    third = client.post("/api/bookings", json=booking_payload(next_monday + timedelta(days=1), 1))
    assert third.status_code == 409
    assert "Weekly booking limit reached. EPCAT" in third.json()["detail"]


def test_weekly_limit_is_case_and_spacing_insensitive(client, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1, tenant_name="EPCAT"))
    client.post("/api/bookings", json=booking_payload(next_monday, 2, tenant_name=" epcat "))
    blocked = client.post("/api/bookings", json=booking_payload(next_monday, 3, tenant_name="EpCat"))
    assert blocked.status_code == 409


def test_weekly_limit_resets_next_week(client, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    client.post("/api/bookings", json=booking_payload(next_monday, 2))
    following = client.post("/api/bookings", json=booking_payload(next_monday + timedelta(days=7), 1))
    assert following.status_code == 201


def test_admin_can_override_the_weekly_limit(client, admin_headers, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    client.post("/api/bookings", json=booking_payload(next_monday, 2))
    override = client.post(
        "/api/bookings",
        json=booking_payload(
            next_monday,
            3,
            override_weekly_limit=True,
            override_reason="Critical business deployment.",
        ),
        headers=admin_headers,
    )
    assert override.status_code == 201, override.text


def test_admin_override_requires_a_reason(client, admin_headers, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    client.post("/api/bookings", json=booking_payload(next_monday, 2))
    response = client.post(
        "/api/bookings",
        json=booking_payload(next_monday, 3, override_weekly_limit=True),
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "override reason is required" in response.json()["detail"]


def test_public_user_cannot_override_the_weekly_limit(client, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    client.post("/api/bookings", json=booking_payload(next_monday, 2))
    response = client.post(
        "/api/bookings",
        json=booking_payload(next_monday, 3, override_weekly_limit=True, override_reason="please"),
    )
    assert response.status_code == 409


def test_cannot_book_a_past_date(client):
    from app.utils.dates import today_local

    response = client.post("/api/bookings", json=booking_payload(today_local() - timedelta(days=3), 1))
    assert response.status_code == 400
    assert "past" in response.json()["detail"]


def test_cannot_book_a_weekend(client, next_monday):
    response = client.post("/api/bookings", json=booking_payload(next_monday + timedelta(days=5), 1))
    assert response.status_code == 400
    assert "Monday to Friday" in response.json()["detail"]


def test_cannot_book_a_slot_beyond_the_configured_grid(client, next_monday):
    response = client.post("/api/bookings", json=booking_payload(next_monday, 9))
    assert response.status_code == 404


def test_pin_must_be_six_digits(client, next_monday):
    response = client.post(
        "/api/bookings",
        json=booking_payload(next_monday, 1, booking_pin="12ab56", confirm_booking_pin="12ab56"),
    )
    assert response.status_code == 422


def test_pin_confirmation_must_match(client, next_monday):
    response = client.post(
        "/api/bookings", json=booking_payload(next_monday, 1, confirm_booking_pin="654321")
    )
    assert response.status_code == 422


def test_invalid_git_repository_is_rejected(client, next_monday):
    response = client.post("/api/bookings", json=booking_payload(next_monday, 1, git_repository="not a url"))
    assert response.status_code == 422


def test_invalid_email_is_rejected(client, next_monday):
    response = client.post("/api/bookings", json=booking_payload(next_monday, 1, requester_email="nope"))
    assert response.status_code == 422


def test_pin_and_token_hashes_are_never_returned(client, next_monday):
    body = client.post("/api/bookings", json=booking_payload(next_monday, 1)).text
    assert "booking_pin" not in body
    assert "pin_hash" not in body
    assert "123456" not in body


def test_public_read_masks_contact_details(client, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    public = client.get(f"/api/bookings/{created['booking']['id']}").json()
    assert public["requester_email"] != "rahul.menon@example.com"
    assert public["requester_email"].endswith("@example.com")
    assert public["verifier_name"] == "Kalyani Sethuraman"


def test_admin_read_shows_full_contact_details(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    detail = client.get(
        f"/api/bookings/{created['booking']['id']}", headers=admin_headers
    ).json()
    assert detail["requester_email"] == "rahul.menon@example.com"
