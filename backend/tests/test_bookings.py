"""Change-record creation, tenant selection and per-record ownership.

A user is a person; a tenant is chosen per change record. One person may
schedule for many tenants, and ownership is decided by created_by_user_id.
"""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload, create_booking, create_tenant, post_booking


def test_authenticated_user_can_schedule_a_change(user, tenant, next_monday):
    response = post_booking(user, booking_payload(tenant, next_monday, 1))
    assert response.status_code == 201, response.text
    booking = response.json()["booking"]
    assert booking["booking_reference"].startswith("PDS-")
    assert booking["status"] == "BOOKED"
    assert booking["is_emergency"] is False
    assert booking["tenant_id"] == tenant


def test_booking_records_the_creating_user(user, tenant, next_monday):
    me = user.get("/api/auth/me").json()
    booking = create_booking(user, tenant, next_monday, 1)
    assert booking["created_by_user_id"] == me["id"]


def test_anonymous_callers_cannot_schedule(anon, tenant, next_monday):
    response = post_booking(anon, booking_payload(tenant, next_monday, 1))
    assert response.status_code == 401


def test_one_user_can_schedule_for_several_tenants(user, admin, next_monday):
    """USER != TENANT: no permanent user/tenant assignment exists."""
    first = create_tenant(admin, "Tenant A", "TEN-A")
    second = create_tenant(admin, "Tenant B", "TEN-B")
    third = create_tenant(admin, "Tenant C", "TEN-C")

    for index, tenant_id in enumerate([first, second, third], start=1):
        booking = create_booking(user, tenant_id, next_monday, index)
        assert booking["tenant_id"] == tenant_id

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    names = {s["booking"]["tenant_name"] for s in board["days"][0]["slots"] if s["booking"]}
    assert names == {"Tenant A", "Tenant B", "Tenant C"}


def test_tenant_must_come_from_the_master_list(user, next_monday):
    missing = post_booking(user, booking_payload(999_999, next_monday, 1))
    assert missing.status_code == 422

    payload = booking_payload(1, next_monday, 1)
    payload.pop("tenant_id")
    assert post_booking(user, payload).status_code == 422


def test_scheduling_never_creates_a_tenant_as_a_side_effect(user, admin, tenant, next_monday):
    before = len(admin.get("/api/admin/tenants").json())
    payload = booking_payload(tenant, next_monday, 1, tenant_name="Brand New Tenant")
    assert post_booking(user, payload).status_code == 201
    assert len(admin.get("/api/admin/tenants").json()) == before


def test_inactive_tenant_is_rejected(user, admin, tenant, next_monday):
    admin.patch(f"/api/admin/tenants/{tenant}/status", json={"is_active": False})
    response = post_booking(user, booking_payload(tenant, next_monday, 1))
    assert response.status_code == 409
    assert "inactive" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #


def test_owner_can_read_and_edit_their_change(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert user.get(f"/api/bookings/{booking['id']}").status_code == 200

    updated = user.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_number="CHG0999999"),
    )
    assert updated.status_code == 200
    assert updated.json()["jira_number"] == "CHG0999999"


def test_another_user_cannot_read_edit_or_cancel(user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)

    assert other_user.get(f"/api/bookings/{booking['id']}").status_code == 403
    assert (
        other_user.put(
            f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1)
        ).status_code
        == 403
    )
    assert (
        other_user.request("DELETE", f"/api/bookings/{booking['id']}", json={}).status_code == 403
    )
    assert other_user.get(f"/api/bookings/{booking['id']}/attachments").status_code == 403


def test_admin_can_read_and_edit_any_change(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert admin.get(f"/api/bookings/{booking['id']}").status_code == 200
    updated = admin.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_number="CHG0777777"),
    )
    assert updated.status_code == 200


def test_owner_can_cancel_and_the_slot_is_released(user, other_user, tenant, other_tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    cancelled = user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    # The freed slot is immediately bookable by somebody else.
    assert post_booking(other_user, booking_payload(other_tenant, next_monday, 1)).status_code == 201


def test_cancelled_change_cannot_be_edited(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    response = user.put(
        f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1)
    )
    assert response.status_code == 400
    assert "cancelled" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Slot rules and validation
# --------------------------------------------------------------------------- #


def test_normal_slot_cannot_be_double_booked(user, other_user, tenant, other_tenant, next_monday):
    create_booking(user, tenant, next_monday, 2)
    clash = post_booking(other_user, booking_payload(other_tenant, next_monday, 2))
    assert clash.status_code == 409
    assert "just been booked" in clash.json()["detail"]


def test_booking_reference_is_sequential_and_unique(user, tenant, other_tenant, next_monday):
    first = create_booking(user, tenant, next_monday, 1)
    second = create_booking(user, other_tenant, next_monday, 2)
    day = next_monday.strftime("%Y%m%d")
    assert first["booking_reference"] == f"PDS-{day}-001"
    assert second["booking_reference"] == f"PDS-{day}-002"


def test_past_dates_and_weekends_are_rejected(user, tenant, next_monday):
    from app.utils.dates import today_local

    past = post_booking(user, booking_payload(tenant, today_local() - timedelta(days=3), 1))
    assert past.status_code == 423
    assert "read-only" in past.json()["detail"]

    weekend = post_booking(user, booking_payload(tenant, next_monday + timedelta(days=5), 1))
    assert weekend.status_code == 400
    assert "Sunday to Thursday" in weekend.json()["detail"]


def test_unknown_slot_is_rejected(user, tenant, next_monday):
    assert post_booking(user, booking_payload(tenant, next_monday, 9)).status_code == 404


def test_field_validation_is_enforced_server_side(user, tenant, next_monday):
    bad_email = booking_payload(tenant, next_monday, 1, requester_email="not-an-email")
    assert post_booking(user, bad_email).status_code == 422

    bad_repo = booking_payload(tenant, next_monday, 1, git_repository="not a url")
    assert post_booking(user, bad_repo).status_code == 422

    bad_jira = booking_payload(tenant, next_monday, 1, jira_url="javascript:alert(1)")
    assert post_booking(user, bad_jira).status_code == 422


def test_justification_and_impacted_region_are_mandatory(user, tenant, next_monday):
    for field in ("justification", "impacted_region"):
        missing = booking_payload(tenant, next_monday, 1)
        del missing[field]
        assert post_booking(user, missing).status_code == 422, field

        blank = booking_payload(tenant, next_monday, 1, **{field: "   "})
        assert post_booking(user, blank).status_code == 422, field


def test_justification_and_impacted_region_round_trip(user, tenant, next_monday):
    booking = create_booking(
        user, tenant, next_monday, 1,
        justification="Regulatory deadline for the Q4 claims release.",
        impacted_region="EMEA",
    )
    assert booking["justification"] == "Regulatory deadline for the Q4 claims release."
    assert booking["impacted_region"] == "EMEA"

    edited = user.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(
            tenant, next_monday, 1,
            justification="Deadline moved forward by the release board.",
            impacted_region="APAC, EMEA",
        ),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["justification"] == "Deadline moved forward by the release board."
    assert edited.json()["impacted_region"] == "APAC, EMEA"


def test_an_edit_cannot_blank_out_justification_or_impacted_region(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    for field in ("justification", "impacted_region"):
        payload = booking_payload(tenant, next_monday, 1, **{field: ""})
        assert user.put(f"/api/bookings/{booking['id']}", json=payload).status_code == 422, field


def test_deployment_description_is_optional(user, tenant, next_monday):
    omitted = booking_payload(tenant, next_monday, 1)
    del omitted["deployment_description"]
    response = post_booking(user, omitted)
    assert response.status_code == 201, response.text
    assert response.json()["booking"]["deployment_description"] == ""

    blank = booking_payload(tenant, next_monday, 2, deployment_description="")
    assert post_booking(user, blank).status_code == 201


def test_emergency_changes_also_require_the_new_fields(admin, tenant, next_monday):
    """business_justification is emergency-only and does not substitute."""
    from conftest import emergency_payload

    payload = emergency_payload(tenant, next_monday)
    del payload["justification"]
    assert post_booking(admin, payload).status_code == 422

    assert post_booking(admin, emergency_payload(tenant, next_monday)).status_code == 201


def test_board_shows_the_owner_so_the_ui_can_mark_my_changes(user, tenant, next_monday):
    me = user.get("/api/auth/me").json()
    create_booking(user, tenant, next_monday, 1)
    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    booked = next(s for s in board["days"][0]["slots"] if s["booking"])
    assert booked["booking"]["created_by_user_id"] == me["id"]


def test_schedule_returns_only_the_requested_week(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    week = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert week["week_start"] == next_monday.isoformat()
    assert [d["weekday"] for d in week["days"]] == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]
    assert week["summary"]["slots_booked"] == 1
    assert week["summary"]["regular_slots_total"] == 20

    other = user.get(f"/api/schedule?week={(next_monday + timedelta(days=7)).isoformat()}").json()
    assert other["summary"]["slots_booked"] == 0
