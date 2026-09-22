"""Emergency changes (an admin-only per-date queue) and holiday blocking.

Emergency changes are deliberately *not* a slot. Any number of them can sit on
the same date, they carry no slot_number, and they never consume normal
deployment capacity or the tenant's weekly quota.
"""
from __future__ import annotations

from datetime import date, timedelta

from conftest import booking_payload, create_booking, emergency_payload, post_booking


def _day(board: dict, index: int = 0) -> dict:
    return board["days"][index]


# --------------------------------------------------------------------------- #
# Emergency queue
# --------------------------------------------------------------------------- #


def test_tenant_user_cannot_create_an_emergency_change(user, tenant, next_monday):
    response = post_booking(user, emergency_payload(tenant, next_monday))
    assert response.status_code == 403
    assert "administrators" in response.json()["detail"].lower()


def test_admin_can_create_an_emergency_change(admin, tenant, next_monday):
    response = post_booking(admin, emergency_payload(tenant, next_monday))
    assert response.status_code == 201, response.text
    booking = response.json()["booking"]
    assert booking["is_emergency"] is True
    assert booking["slot_number"] is None
    assert booking["emergency_reason"]


def test_many_emergency_changes_can_share_one_date(admin, tenant, other_tenant, next_monday):
    """The old one-emergency-slot-per-day limit is gone."""
    for index in range(4):
        response = post_booking(admin, emergency_payload(
                tenant if index % 2 == 0 else other_tenant,
                next_monday,
                jira_number=f"CHG099000{index}",
            ),)
        assert response.status_code == 201, response.text

    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday = _day(board)
    assert len(monday["emergency_bookings"]) == 4
    assert board["summary"]["emergency_changes"] == 4
    # All four are queued on the date and none of them holds a slot.
    assert all(item["slot_number"] is None for item in monday["emergency_bookings"])


def test_emergency_changes_do_not_consume_normal_capacity(admin, user, tenant, next_monday):
    before = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(before)["regular_slots_total"] == 4
    assert len(_day(before)["slots"]) == 4

    for index in range(3):
        post_booking(admin, emergency_payload(tenant, next_monday, jira_number=f"CHG088000{index}"),)

    after = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday = _day(after)
    assert monday["regular_slots_total"] == 4
    assert monday["regular_slots_used"] == 0
    assert len(monday["slots"]) == 4
    # Every normal slot is still free.
    assert all(slot["state"] == "AVAILABLE" for slot in monday["slots"])


def test_emergency_changes_do_not_consume_the_weekly_tenant_quota(admin, user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    # Quota is spent for normal changes...
    assert post_booking(user, booking_payload(tenant, next_monday, 3)).status_code == 409
    # ...but emergency changes are outside it entirely.
    assert post_booking(admin, emergency_payload(tenant, next_monday)).status_code == 201


def test_emergency_change_requires_reason_and_justification(admin, tenant, next_monday):
    no_reason = post_booking(admin, emergency_payload(tenant, next_monday, emergency_reason=""))
    assert no_reason.status_code == 400
    assert "Emergency Reason is required" in no_reason.json()["detail"]

    no_justification = post_booking(admin, emergency_payload(tenant, next_monday, business_justification="  "))
    assert no_justification.status_code == 400
    assert "Business Justification is required" in no_justification.json()["detail"]


def test_only_admins_can_edit_or_cancel_an_emergency_change(admin, user, tenant, next_monday):
    created = post_booking(admin, emergency_payload(tenant, next_monday)).json()
    booking_id = created["booking"]["id"]

    # A tenant user is not the owner and is refused before any rule runs.
    assert user.get(f"/api/bookings/{booking_id}").status_code == 403
    assert (
        user.put(f"/api/bookings/{booking_id}", json=emergency_payload(tenant, next_monday)).status_code
        == 403
    )
    assert user.request("DELETE", f"/api/bookings/{booking_id}", json={}).status_code == 403

    edited = admin.put(
        f"/api/bookings/{booking_id}",
        json=emergency_payload(tenant, next_monday, emergency_approver="Director of Platform"),
    )
    assert edited.status_code == 200
    assert edited.json()["emergency_approver"] == "Director of Platform"
    assert admin.request("DELETE", f"/api/bookings/{booking_id}", json={}).status_code == 200


def test_emergency_changes_are_never_reported_as_locked(admin, tenant, next_monday):
    """Emergency changes are not governed by normal-slot manual freezes."""
    created = post_booking(admin, emergency_payload(tenant, next_monday)).json()
    assert created["booking"]["is_locked"] is False


def test_admin_emergency_bypasses_a_closed_date(admin, tenant, next_monday):
    admin.put("/api/admin/settings", json={"emergency_changes_enabled": False})
    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board)["emergency_open"] is True

    response = post_booking(admin, emergency_payload(tenant, next_monday))
    assert response.status_code == 201, response.text


def test_admin_can_schedule_emergency_on_a_weekend(admin, tenant, next_monday):
    saturday = next_monday + timedelta(days=5)
    response = post_booking(admin, emergency_payload(tenant, saturday))
    assert response.status_code == 201, response.text

    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert len(board["days"]) == 5  # normal board is Sunday-Thursday only
    records = admin.get("/api/admin/bookings?include_cancelled=true").json()
    assert any(item["deployment_date"] == saturday.isoformat() and item["is_emergency"] for item in records)


# --------------------------------------------------------------------------- #
# Holidays
# --------------------------------------------------------------------------- #


def test_full_day_holiday_blocks_normal_changes(admin, user, tenant, next_monday):
    created = admin.post(
        "/api/admin/holidays",
        json={
            "holiday_date": next_monday.isoformat(),
            "name": "Indian Public Holiday",
            "description": "No production deployments available.",
            "is_full_day": True,
            "allow_emergency": True,
        },
    )
    assert created.status_code == 201, created.text

    blocked = post_booking(user, booking_payload(tenant, next_monday, 1))
    assert blocked.status_code == 400
    assert "no production deployments available" in blocked.json()["detail"].lower()

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday = _day(board)
    assert monday["holiday"]["name"] == "Indian Public Holiday"
    assert monday["regular_slots_total"] == 0
    assert all(slot["state"] == "HOLIDAY" for slot in monday["slots"])
    assert board["summary"]["holidays"] == 1


def test_admin_can_book_a_normal_slot_on_a_full_day_holiday(admin, tenant, next_monday):
    admin.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Festival", "is_full_day": True},
    )
    assert post_booking(admin, booking_payload(tenant, next_monday, 1)).status_code == 400
    response = post_booking(admin, booking_payload(tenant, next_monday, 1, manual_override=True, override_reason="Exceptional approved deployment"))
    assert response.status_code == 201, response.text


def test_holiday_can_keep_the_emergency_queue_open(admin, tenant, next_monday):
    admin.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Festival", "allow_emergency": True},
    )
    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board)["emergency_open"] is True
    assert post_booking(admin, emergency_payload(tenant, next_monday)).status_code == 201


def test_admin_emergency_bypasses_holiday_emergency_closure(admin, tenant, next_monday):
    admin.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Festival", "allow_emergency": False},
    )
    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board)["emergency_open"] is True

    response = post_booking(admin, emergency_payload(tenant, next_monday))
    assert response.status_code == 201, response.text


def test_partial_holiday_keeps_normal_slots_open(admin, user, tenant, next_monday):
    admin.post(
        "/api/admin/holidays",
        json={"holiday_date": next_monday.isoformat(), "name": "Half day", "is_full_day": False},
    )
    assert post_booking(user, booking_payload(tenant, next_monday, 1)).status_code == 201


def test_holiday_crud_and_duplicate_protection(admin, next_monday):
    body = {"holiday_date": next_monday.isoformat(), "name": "Placeholder"}
    created = admin.post("/api/admin/holidays", json=body)
    assert created.status_code == 201
    assert admin.post("/api/admin/holidays", json=body).status_code == 409

    holiday_id = created.json()["id"]
    updated = admin.put(
        f"/api/admin/holidays/{holiday_id}",
        json={"holiday_date": next_monday.isoformat(), "name": "Renamed", "is_full_day": True},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"

    assert admin.delete(f"/api/admin/holidays/{holiday_id}").status_code == 204
    assert admin.get("/api/admin/holidays").json() == []


def test_holiday_management_is_admin_only(user, anon, next_monday):
    body = {"holiday_date": next_monday.isoformat(), "name": "Nope"}
    assert anon.post("/api/admin/holidays", json=body).status_code == 401
    assert user.post("/api/admin/holidays", json=body).status_code == 403


# --------------------------------------------------------------------------- #
# Per-date normal slot capacity
#
# The configured default applies to every deployment date; an administrator
# adds or removes slots on one date without disturbing any other.
# --------------------------------------------------------------------------- #


def test_removing_a_slot_reduces_normal_capacity_for_one_date_only(admin, user, tenant, next_monday):
    tuesday = next_monday + timedelta(days=1)
    for _ in range(2):
        response = admin.post(f"/api/admin/day-capacity/{tuesday.isoformat()}/remove-slot")
        assert response.status_code == 200, response.text
    assert response.json() == {
        "capacity_date": tuesday.isoformat(),
        "slot_count": 2,
        "custom_slot_count": 2,
        "max_slot_count": 12,
    }

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board, 0)["regular_slots_total"] == 4  # Monday untouched
    assert _day(board, 0)["custom_slot_count"] is None
    assert _day(board, 1)["regular_slots_total"] == 2
    assert _day(board, 1)["custom_slot_count"] == 2
    assert _day(board, 1)["slots"][2]["state"] == "DISABLED"

    assert post_booking(user, booking_payload(tenant, tuesday, 3)).status_code == 400
    assert post_booking(user, booking_payload(tenant, tuesday, 2)).status_code == 201


def test_adding_a_slot_creates_extra_capacity_for_one_date(admin, user, tenant, next_monday):
    tuesday = next_monday + timedelta(days=1)
    response = admin.post(f"/api/admin/day-capacity/{tuesday.isoformat()}/add-slot")
    assert response.status_code == 200, response.text
    assert response.json()["slot_count"] == 5

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board, 0)["regular_slots_total"] == 4  # Monday untouched
    assert _day(board, 1)["regular_slots_total"] == 5
    assert post_booking(user, booking_payload(tenant, tuesday, 5)).status_code == 201


def test_a_slot_added_to_one_date_is_not_bookable_on_any_other(admin, user, tenant, next_monday):
    """Extra capacity belongs to the date it was added to, and nowhere else."""
    tuesday = next_monday + timedelta(days=1)
    admin.post(f"/api/admin/day-capacity/{tuesday.isoformat()}/add-slot")

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday_slot_5 = next(s for s in _day(board, 0)["slots"] if s["slot_number"] == 5)
    tuesday_slot_5 = next(s for s in _day(board, 1)["slots"] if s["slot_number"] == 5)
    assert monday_slot_5["enabled"] is False and monday_slot_5["bookable"] is False
    assert tuesday_slot_5["enabled"] is True and tuesday_slot_5["bookable"] is True
    assert _day(board, 0)["regular_slots_total"] == 4
    assert _day(board, 1)["regular_slots_total"] == 5

    assert post_booking(user, booking_payload(tenant, next_monday, 5)).status_code == 400
    assert post_booking(user, booking_payload(tenant, tuesday, 5)).status_code == 201


def test_a_slot_holding_a_booking_cannot_be_removed(admin, user, tenant, next_monday):
    tuesday = next_monday + timedelta(days=1)
    assert post_booking(user, booking_payload(tenant, tuesday, 4)).status_code == 201
    response = admin.post(f"/api/admin/day-capacity/{tuesday.isoformat()}/remove-slot")
    assert response.status_code == 409
    assert "Slot 4 is booked" in response.json()["detail"]


def test_day_capacity_can_be_reset_to_the_default(admin, user, next_monday):
    tuesday = next_monday + timedelta(days=1)
    admin.post(f"/api/admin/day-capacity/{tuesday.isoformat()}/remove-slot")
    reset = admin.delete(f"/api/admin/day-capacity/{tuesday.isoformat()}")
    assert reset.status_code == 200, reset.text
    assert reset.json()["custom_slot_count"] is None

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert _day(board, 1)["regular_slots_total"] == 4


def test_only_an_administrator_can_change_day_capacity(anon, user, next_monday):
    tuesday = next_monday + timedelta(days=1)
    path = f"/api/admin/day-capacity/{tuesday.isoformat()}/add-slot"
    assert anon.post(path).status_code == 401
    assert user.post(path).status_code == 403


def test_day_capacity_cannot_be_changed_on_a_read_only_date(admin):
    today = date.today()
    assert admin.post(f"/api/admin/day-capacity/{today.isoformat()}/add-slot").status_code == 423
