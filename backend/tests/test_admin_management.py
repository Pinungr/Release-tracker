"""Administrator capabilities: user management, tenant master, slots, audit."""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload, create_booking, create_tenant, post_booking


def _user_named(admin, username: str) -> dict:
    return next(u for u in admin.get("/api/admin/users").json() if u["username"] == username)


# --------------------------------------------------------------------------- #
# User management
# --------------------------------------------------------------------------- #


def test_user_list_shows_the_management_columns(admin, user):
    rows = admin.get("/api/admin/users").json()
    row = next(u for u in rows if u["username"] == "pinaki")
    assert set(row) >= {
        "id",
        "full_name",
        "username",
        "email",
        "role",
        "is_active",
        "created_at",
    }


def test_user_search_filters_by_name_username_or_email(admin, user, other_user):
    assert len(admin.get("/api/admin/users?search=pinaki").json()) == 1
    assert len(admin.get("/api/admin/users?search=user2@example.com").json()) == 1
    assert admin.get("/api/admin/users?search=nobody").json() == []


def test_role_changes_are_audited(admin, user):
    target = _user_named(admin, "pinaki")
    admin.patch(f"/api/admin/users/{target['id']}/role", json={"role": "ADMIN"})
    audit = admin.get("/api/admin/audit").json()
    event = next(e for e in audit if e["event_type"] == "USER_ROLE_UPDATED")
    assert event["old_values"] == {"role": "TENANT_USER"}
    assert event["new_values"] == {"role": "ADMIN"}
    assert event["admin_username"] == "testadmin"


def test_invalid_role_is_rejected(admin, user):
    target = _user_named(admin, "pinaki")
    response = admin.patch(f"/api/admin/users/{target['id']}/role", json={"role": "SUPERUSER"})
    assert response.status_code == 400


def test_the_bootstrap_administrator_is_the_protected_owner(admin):
    assert _user_named(admin, "testadmin")["is_owner"] is True
    assert [u["username"] for u in admin.get("/api/admin/users").json() if u["is_owner"]] == [
        "testadmin"
    ]


def test_the_owner_account_cannot_be_targeted_by_anyone(admin):
    """Not even by the owner: their own credentials are self-service only."""
    me = _user_named(admin, "testadmin")

    demote = admin.patch(f"/api/admin/users/{me['id']}/role", json={"role": "TENANT_USER"})
    assert demote.status_code == 403
    assert "owner account is protected" in demote.json()["detail"]

    assert admin.patch(
        f"/api/admin/users/{me['id']}/status", json={"is_active": False}
    ).status_code == 403
    assert admin.post(
        f"/api/admin/users/{me['id']}/reset-password",
        json={"new_password": "Hijacked!123", "confirm_new_password": "Hijacked!123"},
    ).status_code == 403


def test_the_owner_can_demote_another_administrator(admin, user):
    promoted = _user_named(admin, "pinaki")
    assert admin.patch(
        f"/api/admin/users/{promoted['id']}/role", json={"role": "ADMIN"}
    ).status_code == 200
    assert admin.patch(
        f"/api/admin/users/{promoted['id']}/role", json={"role": "TENANT_USER"}
    ).status_code == 200
    assert _user_named(admin, "pinaki")["role"] == "TENANT_USER"


def test_user_management_is_admin_only(anon, user):
    assert anon.get("/api/admin/users").status_code == 401
    assert user.get("/api/admin/users").status_code == 403
    assert user.patch("/api/admin/users/1/role", json={"role": "ADMIN"}).status_code == 403


# --------------------------------------------------------------------------- #
# Tenant master
# --------------------------------------------------------------------------- #


def test_admin_can_create_edit_and_deactivate_a_tenant(admin, user):
    created = admin.post("/api/admin/tenants", json={"name": "Encounters", "tenant_code": "ENC"})
    assert created.status_code == 201
    tenant_id = created.json()["id"]

    updated = admin.put(
        f"/api/admin/tenants/{tenant_id}",
        json={"name": "Encounters Platform", "tenant_code": "ENC", "description": "Claims"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Encounters Platform"

    # Active tenants are what the scheduling form offers.
    assert any(t["id"] == tenant_id for t in user.get("/api/tenants/active").json())

    admin.patch(f"/api/admin/tenants/{tenant_id}/status", json={"is_active": False})
    assert all(t["id"] != tenant_id for t in user.get("/api/tenants/active").json())

    admin.patch(f"/api/admin/tenants/{tenant_id}/status", json={"is_active": True})
    assert any(t["id"] == tenant_id for t in user.get("/api/tenants/active").json())


def test_duplicate_tenant_name_or_code_is_rejected(admin, tenant):
    assert (
        admin.post("/api/admin/tenants", json={"name": "EPCAT", "tenant_code": "OTHER"}).status_code
        == 409
    )
    assert (
        admin.post("/api/admin/tenants", json={"name": "Other", "tenant_code": "EPCAT"}).status_code
        == 409
    )


def test_tenant_management_is_admin_only(anon, user):
    body = {"name": "Nope", "tenant_code": "NOPE"}
    assert anon.post("/api/admin/tenants", json=body).status_code == 401
    assert user.post("/api/admin/tenants", json=body).status_code == 403


# --------------------------------------------------------------------------- #
# Settings and slot configuration
# --------------------------------------------------------------------------- #


def test_settings_keep_the_poc_defaults(admin):
    settings = admin.get("/api/admin/settings").json()
    assert settings["regular_slots_per_day"] == 4
    assert settings["weekly_booking_limit"] == 2
    assert settings["max_file_size_mb"] == 20


def test_default_slots_use_overnight_window(admin):
    slots = admin.get("/api/admin/slots").json()
    assert len(slots) == 4
    assert all(slot["start_time"] == "21:00:00" for slot in slots)
    assert all(slot["end_time"] == "05:00:00" for slot in slots)


def test_increasing_slots_per_day_creates_missing_rows(admin, user, next_monday):
    response = admin.put("/api/admin/settings", json={"regular_slots_per_day": 6})
    assert response.status_code == 200, response.text
    assert response.json()["regular_slots_per_day"] == 6

    slots = admin.get("/api/admin/slots").json()
    assert [slot["slot_number"] for slot in slots] == [1, 2, 3, 4, 5, 6]
    assert slots[4]["start_time"] == "21:00:00"
    assert slots[4]["end_time"] == "05:00:00"
    assert slots[5]["start_time"] == "21:00:00"
    assert slots[5]["end_time"] == "05:00:00"

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert len(board["days"][0]["slots"]) == 6
    assert board["days"][0]["slots"][5]["slot_number"] == 6


def test_reducing_slots_per_day_shrinks_the_board(admin, user, tenant, next_monday):
    admin.put("/api/admin/settings", json={"regular_slots_per_day": 3})
    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert board["days"][0]["regular_slots_total"] == 3
    assert board["days"][0]["slots"][3]["state"] == "DISABLED"
    assert post_booking(user, booking_payload(tenant, next_monday, 4)).status_code == 400


def test_admin_can_book_a_disabled_normal_slot(admin, tenant, next_monday):
    admin.put("/api/admin/settings", json={"regular_slots_per_day": 3})
    assert post_booking(admin, booking_payload(tenant, next_monday, 4)).status_code == 400
    response = post_booking(admin, booking_payload(tenant, next_monday, 4, manual_override=True, override_reason="Exceptional approved deployment"))
    assert response.status_code == 201, response.text


def test_admin_can_book_future_weekends_but_not_past_dates(admin, tenant, next_monday):
    saturday = next_monday + timedelta(days=6)
    assert post_booking(admin, booking_payload(tenant, saturday, 1)).status_code == 400
    weekend = post_booking(admin, booking_payload(tenant, saturday, 1, manual_override=True, override_reason="Exceptional approved deployment"))
    assert weekend.status_code == 201, weekend.text

    # Historical dates are immutable for everyone, including administrators.
    past_monday = next_monday - timedelta(days=21)
    past = post_booking(admin, booking_payload(tenant, past_monday, 1))
    assert past.status_code == 423
    assert "read-only" in past.json()["detail"]


def test_slot_configuration_can_be_renamed_and_retimed(admin, user, next_monday):
    slots = admin.get("/api/admin/slots").json()
    assert len(slots) == 4
    assert all("is_emergency" not in slot for slot in slots), "slots are normal-only now"

    slots[0]["name"] = "Early Window"
    slots[0]["start_time"] = "06:00:00"
    slots[0]["end_time"] = "08:00:00"
    assert admin.put("/api/admin/slots", json={"slots": slots}).status_code == 200

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    first = board["days"][0]["slots"][0]
    assert first["name"] == "Early Window"
    assert first["time_label"] == "06:00 AM - 08:00 AM"


def test_overnight_slot_window_is_allowed(admin, user, next_monday):
    slots = admin.get("/api/admin/slots").json()
    slots[0]["start_time"] = "21:00:00"
    slots[0]["end_time"] = "05:00:00"
    assert admin.put("/api/admin/slots", json={"slots": slots}).status_code == 200

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert board["days"][0]["slots"][0]["time_label"] == "09:00 PM - 05:00 AM"


def test_slot_start_and_end_cannot_be_identical(admin):
    slots = admin.get("/api/admin/slots").json()
    slots[0]["start_time"] = "21:00:00"
    slots[0]["end_time"] = "21:00:00"
    assert admin.put("/api/admin/slots", json={"slots": slots}).status_code == 422


def test_a_slot_with_upcoming_changes_cannot_be_removed(admin, user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 4)
    slots = [s for s in admin.get("/api/admin/slots").json() if s["slot_number"] != 4]
    response = admin.put("/api/admin/slots", json={"slots": slots})
    assert response.status_code == 400
    assert "Cannot remove slot 4" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Booking administration
# --------------------------------------------------------------------------- #


def test_admin_can_move_a_change_to_another_slot(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = admin.post(
        f"/api/admin/bookings/{booking['id']}/move",
        json={
            "deployment_date": (next_monday + timedelta(days=2)).isoformat(),
            "slot_number": 3,
            "override_reason": "Requested by the release manager.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["slot_number"] == 3

    audit = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    assert audit[0]["event_type"] == "SLOT_CHANGED"


def test_admin_cannot_move_a_change_onto_an_occupied_slot(admin, user, tenant, other_tenant, next_monday):
    first = create_booking(user, tenant, next_monday, 1)
    create_booking(user, other_tenant, next_monday, 2)
    response = admin.post(
        f"/api/admin/bookings/{first['id']}/move",
        json={"deployment_date": next_monday.isoformat(), "slot_number": 2},
    )
    assert response.status_code == 409






def test_derived_and_future_statuses_cannot_be_set(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    for value in ("LOCKED", "SUCCESSFUL", "ROLLED_BACK"):
        response = admin.post(
            f"/api/admin/bookings/{booking['id']}/status", json={"status": value}
        )
        assert response.status_code == 400, value



# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


def test_audit_records_the_booking_lifecycle_without_secrets(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    user.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_number="CHG0111111"),
    )
    user.request("DELETE", f"/api/bookings/{booking['id']}", json={})

    events = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    types = [e["event_type"] for e in events]
    assert "BOOKING_CREATED" in types
    assert "BOOKING_EDITED" in types
    assert "BOOKING_CANCELLED" in types
    assert all(e["actor_type"] in {"USER", "ADMIN", "SYSTEM"} for e in events)
    assert "password" not in admin.get("/api/admin/audit").text.lower()


def test_audit_is_admin_only(anon, user):
    assert anon.get("/api/admin/audit").status_code == 401
    assert user.get("/api/admin/audit").status_code == 403


def test_past_booking_is_read_only_even_for_admin(
    admin, user, other_user, tenant, next_monday, monkeypatch
):
    import io
    from app.services import booking_service, presenters

    booking = create_booking(user, tenant, next_monday, 1)
    rm_user = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "user2")
    assert admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={"user_ids": [rm_user["id"]]},
    ).status_code == 200

    historical_today = next_monday + timedelta(days=1)
    monkeypatch.setattr(booking_service, "today_local", lambda: historical_today)
    monkeypatch.setattr(presenters, "today_local", lambda: historical_today)

    detail = admin.get(f"/api/bookings/{booking['id']}")
    assert detail.status_code == 200
    assert detail.json()["is_past"] is True
    assert detail.json()["can_edit"] is False

    edit = admin.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_number="JIRA-HISTORICAL"),
    )
    assert edit.status_code == 423

    move = admin.post(
        f"/api/admin/bookings/{booking['id']}/move",
        json={
            "deployment_date": (historical_today + timedelta(days=2)).isoformat(),
            "slot_number": 2,
            "override_reason": None,
        },
    )
    assert move.status_code == 423

    assign = admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={"user_ids": [rm_user["id"]]},
    )
    assert assign.status_code == 423

    start_work = other_user.post(
        f"/api/bookings/{booking['id']}/start-work",
        json={"change_number": "CHG-HIST-001"},
    )
    assert start_work.status_code == 423

    status_change = admin.post(
        f"/api/admin/bookings/{booking['id']}/status",
        json={"status": "COMPLETED", "override_reason": "historical test"},
    )
    assert status_change.status_code == 423

    cancel = admin.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert cancel.status_code == 423

    upload = admin.post(
        f"/api/bookings/{booking['id']}/attachments",
        data={"category": "TEST_RESULTS"},
        files={"file": ("plan.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert upload.status_code == 423
