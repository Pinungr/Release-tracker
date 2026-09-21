"""Regression coverage for RM assignment, Change No. and permanent audit retention."""
from __future__ import annotations

from conftest import booking_payload, create_booking, post_booking


def test_jira_number_is_optional_by_default(user, tenant, next_monday):
    payload = booking_payload(tenant, next_monday, 1)
    payload.pop("jira_number")
    response = post_booking(user, payload)
    assert response.status_code == 201, response.text
    assert response.json()["booking"]["jira_number"] is None


def test_admin_can_require_jira_number_via_booking_rules(admin, user, tenant, next_monday):
    updated = admin.put("/api/admin/settings", json={"jira_required_at_booking": True})
    assert updated.status_code == 200, updated.text

    payload = booking_payload(tenant, next_monday, 1)
    payload.pop("jira_number")
    response = post_booking(user, payload)
    assert response.status_code == 422
    assert "Jira No. is required" in response.json()["detail"]


def test_admin_assigns_rm_and_assigned_user_starts_work(
    admin, user, other_user, tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1, jira_number="JIRA-777")
    rm = other_user.get("/api/auth/me").json()

    assigned = admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={"user_ids": [rm["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["jira_number"] == "JIRA-777"
    assert body["change_number"] is None
    assert [u["user_id"] for u in body["assigned_users"]] == [rm["id"]]

    # Assignment grants read/start-work access, not booking ownership.
    assert other_user.get(f"/api/bookings/{booking['id']}").status_code == 200
    assert (
        other_user.put(
            f"/api/bookings/{booking['id']}",
            json=booking_payload(tenant, next_monday, 1, jira_number="JIRA-CHANGED"),
        ).status_code
        == 403
    )

    started = other_user.post(
        f"/api/bookings/{booking['id']}/start-work",
        json={"change_number": "CHG009001"},
    )
    assert started.status_code == 200, started.text
    started_body = started.json()
    assert started_body["status"] == "IN_PROGRESS"
    assert started_body["jira_number"] == "JIRA-777"
    assert started_body["change_number"] == "CHG009001"
    assert started_body["work_started_by_user_id"] == rm["id"]


def test_unassigned_user_cannot_add_change_number(user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = other_user.post(
        f"/api/bookings/{booking['id']}/start-work",
        json={"change_number": "CHG009002"},
    )
    assert response.status_code == 403


def test_booking_owner_cannot_be_selected_as_rm(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    owner = user.get("/api/auth/me").json()
    response = admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={"user_ids": [owner["id"]]},
    )
    assert response.status_code == 422


def test_hard_delete_preserves_complete_audit_history(
    admin, user, other_user, tenant, next_monday
):
    booking = create_booking(user, tenant, next_monday, 1, jira_number="JIRA-AUDIT-1")
    rm = other_user.get("/api/auth/me").json()
    admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={"user_ids": [rm["id"]]},
    )
    other_user.post(
        f"/api/bookings/{booking['id']}/start-work",
        json={"change_number": "CHG-AUDIT-1"},
    )

    reference = booking["booking_reference"]
    before = [e for e in admin.get("/api/admin/audit?limit=500").json() if e["booking_reference"] == reference]
    before_types = {e["event_type"] for e in before}
    assert {"BOOKING_CREATED", "RM_USERS_ASSIGNED", "WORK_STARTED"}.issubset(before_types)

    deleted = admin.delete(f"/api/admin/bookings/{booking['id']}")
    assert deleted.status_code == 204, deleted.text

    after = [e for e in admin.get("/api/admin/audit?limit=500").json() if e["booking_reference"] == reference]
    after_types = {e["event_type"] for e in after}
    assert before_types.issubset(after_types)
    assert "BOOKING_DELETED" in after_types
    assert len(after) == len(before) + 1
