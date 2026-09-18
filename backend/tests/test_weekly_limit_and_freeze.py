"""The two rules tenants feel most: the weekly tenant quota and the freeze.

The weekly limit counts change records **per tenant**, not per user, and the
freeze window is 48 hours by default.
"""
from __future__ import annotations

from datetime import timedelta

from conftest import booking_payload, create_booking, create_tenant


def _set_freeze_hours(admin, hours: int) -> None:
    response = admin.put("/api/admin/settings", json={"booking_freeze_hours": hours})
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# Weekly tenant limit
# --------------------------------------------------------------------------- #


def test_default_limit_is_two_per_tenant_per_week(user, admin, tenant):
    assert admin.get("/api/admin/settings").json()["weekly_booking_limit"] == 2


def test_third_change_for_the_same_tenant_is_blocked(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    third = user.post("/api/bookings", json=booking_payload(tenant, next_monday, 3))
    assert third.status_code == 409
    assert "Weekly booking limit reached. EPCAT" in third.json()["detail"]


def test_the_quota_is_per_tenant_not_per_user(user, other_user, tenant, next_monday):
    """User A and User B scheduling for the same tenant share one quota."""
    create_booking(user, tenant, next_monday, 1)
    create_booking(other_user, tenant, next_monday, 2)

    blocked = user.post("/api/bookings", json=booking_payload(tenant, next_monday, 3))
    assert blocked.status_code == 409
    also_blocked = other_user.post("/api/bookings", json=booking_payload(tenant, next_monday, 4))
    assert also_blocked.status_code == 409


def test_each_tenant_has_an_independent_quota(user, admin, tenant, next_monday):
    other = create_tenant(admin, "Encounters", "ENC")
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)

    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 3)).status_code == 409
    # A different tenant still has its full quota, for the same person.
    assert user.post("/api/bookings", json=booking_payload(other, next_monday, 3)).status_code == 201
    assert user.post("/api/bookings", json=booking_payload(other, next_monday, 4)).status_code == 201


def test_the_quota_spans_the_whole_working_week(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday + timedelta(days=1), 1)
    blocked = user.post(
        "/api/bookings", json=booking_payload(tenant, next_monday + timedelta(days=4), 1)
    )
    assert blocked.status_code == 409


def test_the_quota_resets_the_following_week(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    following = user.post(
        "/api/bookings", json=booking_payload(tenant, next_monday + timedelta(days=7), 1)
    )
    assert following.status_code == 201


def test_a_cancelled_change_frees_quota(user, tenant, next_monday):
    first = create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 3)).status_code == 409

    user.request("DELETE", f"/api/bookings/{first['id']}", json={})
    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 3)).status_code == 201


def test_admin_can_override_the_weekly_limit_with_a_reason(admin, user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)

    without_reason = admin.post(
        "/api/bookings",
        json=booking_payload(tenant, next_monday, 3, override_weekly_limit=True),
    )
    assert without_reason.status_code == 400
    assert "override reason is required" in without_reason.json()["detail"]

    with_reason = admin.post(
        "/api/bookings",
        json=booking_payload(
            tenant,
            next_monday,
            3,
            override_weekly_limit=True,
            override_reason="Critical business deployment.",
        ),
    )
    assert with_reason.status_code == 201

    audit = admin.get("/api/admin/audit").json()
    assert any(e["override_reason"] == "Critical business deployment." for e in audit)


def test_a_tenant_user_cannot_override_the_limit(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    response = user.post(
        "/api/bookings",
        json=booking_payload(
            tenant, next_monday, 3, override_weekly_limit=True, override_reason="please"
        ),
    )
    assert response.status_code == 409


def test_the_limit_is_configurable(admin, user, tenant, next_monday):
    admin.put("/api/admin/settings", json={"weekly_booking_limit": 1})
    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 1)).status_code == 201
    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 2)).status_code == 409


# --------------------------------------------------------------------------- #
# 48-hour freeze window
# --------------------------------------------------------------------------- #


def test_freeze_window_defaults_to_48_hours(admin):
    assert admin.get("/api/admin/settings").json()["booking_freeze_hours"] == 48


def test_owner_can_edit_and_cancel_outside_the_window(user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    detail = user.get(f"/api/bookings/{booking['id']}").json()
    assert detail["is_locked"] is False
    assert detail["can_edit"] is True

    assert user.put(
        f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1)
    ).status_code == 200


def test_owner_is_blocked_inside_the_window(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _set_freeze_hours(admin, 720)  # 30 days: the change is now frozen

    edit = user.put(f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1))
    assert edit.status_code == 423
    assert "Changes are disabled within 720 hours" in edit.json()["detail"]

    cancel = user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert cancel.status_code == 423

    assert user.get(f"/api/bookings/{booking['id']}").json()["is_locked"] is True


def test_admin_can_edit_inside_the_window_with_a_reason(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    _set_freeze_hours(admin, 720)

    without_reason = admin.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_change="CHG0777777"),
    )
    assert without_reason.status_code == 400

    with_reason = admin.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(
            tenant,
            next_monday,
            1,
            jira_change="CHG0777777",
            override_reason="Critical business deployment.",
        ),
    )
    assert with_reason.status_code == 200

    audit = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    assert any(e["override_reason"] == "Critical business deployment." for e in audit)


def test_locked_change_also_blocks_document_upload_for_the_owner(admin, user, tenant, next_monday):
    import io

    booking = create_booking(user, tenant, next_monday, 1)
    _set_freeze_hours(admin, 720)
    response = user.post(
        f"/api/bookings/{booking['id']}/attachments",
        data={"category": "TEST_RESULTS"},
        files={"file": ("plan.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert response.status_code == 423
