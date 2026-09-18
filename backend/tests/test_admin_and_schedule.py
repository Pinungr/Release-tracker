"""Admin authentication, configuration, booking management and the board."""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload, emergency_payload

OWNER = {"requester_email": "rahul.menon@example.com", "booking_pin": "123456"}


def test_admin_login_succeeds_and_issues_a_token(client):
    response = client.post(
        "/api/admin/login", json={"username": "testadmin", "password": "Sup3r-Secret-Pass"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "testadmin"
    assert body["expires_in"] > 0
    assert "password" not in response.text


def test_admin_login_rejects_bad_credentials(client):
    bad_password = client.post(
        "/api/admin/login", json={"username": "testadmin", "password": "wrong"}
    )
    unknown_user = client.post("/api/admin/login", json={"username": "ghost", "password": "wrong"})
    assert bad_password.status_code == unknown_user.status_code == 401
    # Identical message: no user enumeration.
    assert bad_password.json()["detail"] == unknown_user.json()["detail"]


def test_admin_password_is_stored_hashed(db):
    from sqlalchemy import select

    from app.models import AdminUser

    user = db.scalars(select(AdminUser).where(AdminUser.username == "testadmin")).first()
    assert user is not None
    assert "Sup3r-Secret-Pass" not in user.password_hash
    assert user.password_hash.startswith("$2b$")


def test_admin_login_is_rate_limited(client):
    statuses = [
        client.post(
            "/api/admin/login", json={"username": "testadmin", "password": "wrong"}
        ).status_code
        for _ in range(10)
    ]
    assert 429 in statuses


def test_admin_endpoints_reject_anonymous_and_garbage_tokens(client):
    assert client.get("/api/admin/settings").status_code == 401
    assert (
        client.get("/api/admin/settings", headers={"Authorization": "Bearer nonsense"}).status_code
        == 401
    )
    assert client.get("/api/admin/audit").status_code == 401
    assert client.get("/api/admin/slots").status_code == 401


def test_logout_invalidates_the_token(client, admin_headers):
    assert client.get("/api/admin/me", headers=admin_headers).status_code == 200
    assert client.post("/api/admin/logout", headers=admin_headers).status_code == 204
    assert client.get("/api/admin/me", headers=admin_headers).status_code == 401


def test_settings_round_trip(client, admin_headers):
    defaults = client.get("/api/admin/settings", headers=admin_headers).json()
    assert defaults["regular_slots_per_day"] == 4
    assert defaults["weekly_booking_limit"] == 2
    assert defaults["booking_freeze_hours"] == 48
    assert defaults["max_file_size_mb"] == 20

    updated = client.put(
        "/api/admin/settings",
        json={"weekly_booking_limit": 3, "regular_slots_per_day": 3},
        headers=admin_headers,
    ).json()
    assert updated["weekly_booking_limit"] == 3
    assert client.get("/api/config").json()["weekly_booking_limit"] == 3


def test_reducing_slots_per_day_shrinks_the_board(client, admin_headers, next_monday):
    client.put("/api/admin/settings", json={"regular_slots_per_day": 3}, headers=admin_headers)
    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert schedule["days"][0]["regular_slots_total"] == 3
    assert schedule["days"][0]["slots"][3]["state"] == "DISABLED"
    assert client.post("/api/bookings", json=booking_payload(next_monday, 4)).status_code == 400


def test_weekly_limit_setting_is_enforced(client, admin_headers, next_monday):
    client.put("/api/admin/settings", json={"weekly_booking_limit": 1}, headers=admin_headers)
    assert client.post("/api/bookings", json=booking_payload(next_monday, 1)).status_code == 201
    assert client.post("/api/bookings", json=booking_payload(next_monday, 2)).status_code == 409


def test_emergency_slot_can_be_disabled_globally(client, admin_headers, next_monday):
    client.put("/api/admin/settings", json={"emergency_slot_enabled": False}, headers=admin_headers)
    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert schedule["days"][0]["slots"][4]["state"] == "DISABLED"
    assert (
        client.post(
            "/api/bookings", json=emergency_payload(next_monday), headers=admin_headers
        ).status_code
        == 400
    )


def test_slot_configuration_can_be_changed(client, admin_headers, next_monday):
    slots = client.get("/api/admin/slots", headers=admin_headers).json()
    assert len(slots) == 5
    slots[0]["name"] = "Early Window"
    slots[0]["start_time"] = "06:00:00"
    slots[0]["end_time"] = "08:00:00"
    response = client.put("/api/admin/slots", json={"slots": slots}, headers=admin_headers)
    assert response.status_code == 200, response.text

    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    first = schedule["days"][0]["slots"][0]
    assert first["name"] == "Early Window"
    assert first["time_label"] == "06:00 AM - 08:00 AM"


def test_slot_end_must_follow_slot_start(client, admin_headers):
    slots = client.get("/api/admin/slots", headers=admin_headers).json()
    slots[0]["end_time"] = "05:00:00"
    response = client.put("/api/admin/slots", json={"slots": slots}, headers=admin_headers)
    assert response.status_code == 422


def test_cannot_remove_a_slot_that_has_upcoming_bookings(client, admin_headers, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 4))
    slots = client.get("/api/admin/slots", headers=admin_headers).json()
    remaining = [s for s in slots if s["slot_number"] != 4]
    response = client.put("/api/admin/slots", json={"slots": remaining}, headers=admin_headers)
    assert response.status_code == 400
    assert "Cannot remove slot 4" in response.json()["detail"]


def test_admin_can_move_a_booking_to_another_slot(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    response = client.post(
        f"/api/admin/bookings/{booking_id}/move",
        json={
            "deployment_date": (next_monday + timedelta(days=2)).isoformat(),
            "slot_number": 3,
            "override_reason": "Requested by the release manager.",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["slot_number"] == 3

    audit = client.get(f"/api/admin/audit?booking_id={booking_id}", headers=admin_headers).json()
    assert audit[0]["event_type"] == "SLOT_CHANGED"


def test_admin_cannot_move_a_booking_onto_an_occupied_slot(client, admin_headers, next_monday):
    first = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    client.post("/api/bookings", json=booking_payload(next_monday, 2, tenant_name="Encounters"))
    response = client.post(
        f"/api/admin/bookings/{first['booking']['id']}/move",
        json={"deployment_date": next_monday.isoformat(), "slot_number": 2},
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_admin_can_reassign_a_booking(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    response = client.post(
        f"/api/admin/bookings/{created['booking']['id']}/reassign",
        json={"tenant_name": "Encounters", "verifier_name": "Siva Naga Raju"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["tenant_name"] == "Encounters"
    assert response.json()["verifier_name"] == "Siva Naga Raju"


def test_admin_can_hard_delete_a_booking(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    assert client.delete(f"/api/admin/bookings/{booking_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/bookings/{booking_id}").status_code == 404
    audit = client.get("/api/admin/audit", headers=admin_headers).json()
    assert any(e["event_type"] == "BOOKING_DELETED" for e in audit)


def test_completing_a_booking_requires_the_mandatory_documents(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]

    blocked = client.post(
        f"/api/admin/bookings/{booking_id}/status",
        json={"status": "COMPLETED"},
        headers=admin_headers,
    )
    assert blocked.status_code == 400
    assert "Required deployment document missing" in blocked.json()["detail"]

    # An administrator may still sign it off by recording a reason.
    forced = client.post(
        f"/api/admin/bookings/{booking_id}/status",
        json={"status": "COMPLETED", "override_reason": "Paperwork filed in the change record."},
        headers=admin_headers,
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "COMPLETED"


def test_derived_and_future_statuses_cannot_be_set(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    for status_value in ("LOCKED", "SUCCESSFUL", "ROLLED_BACK"):
        response = client.post(
            f"/api/admin/bookings/{created['booking']['id']}/status",
            json={"status": status_value},
            headers=admin_headers,
        )
        assert response.status_code == 400, status_value


def test_audit_history_records_the_lifecycle(client, admin_headers, next_monday):
    created = client.post("/api/bookings", json=booking_payload(next_monday, 1)).json()
    booking_id = created["booking"]["id"]
    client.request("DELETE", f"/api/bookings/{booking_id}", json={"credentials": OWNER})
    events = client.get(f"/api/admin/audit?booking_id={booking_id}", headers=admin_headers).json()
    types = [e["event_type"] for e in events]
    assert "BOOKING_CREATED" in types
    assert "BOOKING_CANCELLED" in types
    assert all("pin" not in (e["new_values"] or {}) for e in events)


def test_schedule_returns_only_the_requested_week(client, next_monday):
    client.post("/api/bookings", json=booking_payload(next_monday, 1))
    this_week = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert this_week["week_start"] == next_monday.isoformat()
    assert this_week["week_end"] == (next_monday + timedelta(days=4)).isoformat()
    assert len(this_week["days"]) == 5
    assert [d["weekday"] for d in this_week["days"]] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]
    assert this_week["summary"]["slots_booked"] == 1
    assert this_week["summary"]["regular_slots_total"] == 20
    assert this_week["summary"]["regular_slots_available"] == 19
    assert this_week["summary"]["emergency_slots_total"] == 5

    other = client.get(f"/api/schedule?week={(next_monday + timedelta(days=7)).isoformat()}").json()
    assert other["summary"]["slots_booked"] == 0


def test_schedule_accepts_any_day_inside_the_week(client, next_monday):
    wednesday = next_monday + timedelta(days=2)
    assert (
        client.get(f"/api/schedule?week={wednesday.isoformat()}").json()["week_start"]
        == next_monday.isoformat()
    )


def test_schedule_rejects_a_malformed_week(client):
    assert client.get("/api/schedule?week=not-a-date").status_code == 422


def test_public_config_exposes_no_secrets(client):
    body = client.get("/api/config").json()
    assert set(body) == {
        "weekly_booking_limit",
        "booking_freeze_hours",
        "max_file_size_mb",
        "mandatory_documents",
        "document_catalog",
        "technologies",
    }
    assert "Databricks" in body["technologies"]


def test_health_endpoint(client):
    assert client.get("/api/health").json()["status"] == "ok"
