"""Weekly tenant quota and administrator-controlled manual slot freezing.

The weekly limit counts change records **per tenant**, not per user. Normal
users are locked only when an administrator explicitly freezes a slot.
"""
from __future__ import annotations

from datetime import date, timedelta

from conftest import booking_payload, create_booking, create_tenant, post_booking



# --------------------------------------------------------------------------- #
# Weekly tenant limit
# --------------------------------------------------------------------------- #


def test_default_limit_is_two_per_tenant_per_week(user, admin, tenant):
    assert admin.get("/api/admin/settings").json()["weekly_booking_limit"] == 2


def test_third_change_for_the_same_tenant_is_blocked(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    third = post_booking(user, booking_payload(tenant, next_monday, 3))
    assert third.status_code == 409
    assert "Weekly booking limit reached. EPCAT" in third.json()["detail"]


def test_the_quota_is_per_tenant_not_per_user(user, other_user, tenant, next_monday):
    """User A and User B scheduling for the same tenant share one quota."""
    create_booking(user, tenant, next_monday, 1)
    create_booking(other_user, tenant, next_monday, 2)

    blocked = post_booking(user, booking_payload(tenant, next_monday, 3))
    assert blocked.status_code == 409
    also_blocked = post_booking(other_user, booking_payload(tenant, next_monday, 4))
    assert also_blocked.status_code == 409


def test_each_tenant_has_an_independent_quota(user, admin, tenant, next_monday):
    other = create_tenant(admin, "Encounters", "ENC")
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)

    assert post_booking(user, booking_payload(tenant, next_monday, 3)).status_code == 409
    # A different tenant still has its full quota, for the same person.
    assert post_booking(user, booking_payload(other, next_monday, 3)).status_code == 201
    assert post_booking(user, booking_payload(other, next_monday, 4)).status_code == 201


def test_the_quota_spans_the_whole_working_week(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday + timedelta(days=1), 1)
    blocked = post_booking(user, booking_payload(tenant, next_monday + timedelta(days=4), 1))
    assert blocked.status_code == 409


def test_the_quota_resets_the_following_week(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    following = post_booking(user, booking_payload(tenant, next_monday + timedelta(days=7), 1))
    assert following.status_code == 201


def test_a_cancelled_change_frees_quota(user, tenant, next_monday):
    first = create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    assert post_booking(user, booking_payload(tenant, next_monday, 3)).status_code == 409

    user.request("DELETE", f"/api/bookings/{first['id']}", json={})
    assert post_booking(user, booking_payload(tenant, next_monday, 3)).status_code == 201


def test_admin_automatically_bypasses_the_weekly_limit(admin, user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)

    response = post_booking(admin, booking_payload(tenant, next_monday, 3),)
    assert response.status_code == 201, response.text

    audit = admin.get("/api/admin/audit").json()
    assert any(
        e["override_reason"] == "Administrator automatic override: tenant weekly booking limit."
        for e in audit
    )


def test_a_tenant_user_cannot_override_the_limit(user, tenant, next_monday):
    create_booking(user, tenant, next_monday, 1)
    create_booking(user, tenant, next_monday, 2)
    response = post_booking(user, booking_payload(
            tenant, next_monday, 3, override_weekly_limit=True, override_reason="please"
        ),)
    assert response.status_code == 409


def test_the_limit_is_configurable(admin, user, tenant, next_monday):
    admin.put("/api/admin/settings", json={"weekly_booking_limit": 1})
    assert post_booking(user, booking_payload(tenant, next_monday, 1)).status_code == 201
    assert post_booking(user, booking_payload(tenant, next_monday, 2)).status_code == 409


# --------------------------------------------------------------------------- #
# Administrator-controlled manual slot freeze
# --------------------------------------------------------------------------- #


def test_automatic_freeze_is_disabled(admin):
    settings = admin.get("/api/schedule").json()["settings"]
    assert settings["booking_freeze_dates"] == 0


def test_future_slot_is_open_until_admin_freezes_it(user, admin, tenant, next_monday):
    assert post_booking(user, booking_payload(tenant, next_monday, 1)).status_code == 201


def test_admin_can_freeze_an_empty_slot_and_user_cannot_book_it(user, admin, tenant, next_monday):
    frozen = admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    assert frozen.status_code == 200, frozen.text

    blocked = post_booking(user, booking_payload(tenant, next_monday, 1))
    assert blocked.status_code == 423
    assert "manually frozen" in blocked.json()["detail"].lower()

    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    day = next(d for d in board["days"] if d["day"] == next_monday.isoformat())
    slot = next(s for s in day["slots"] if s["slot_number"] == 1)
    assert slot["manually_frozen"] is True
    assert slot["bookable"] is False


def test_admin_can_book_a_manually_frozen_future_slot(admin, tenant, next_monday):
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    created = post_booking(admin, booking_payload(tenant, next_monday, 1))
    assert created.status_code == 201, created.text


def test_owner_is_blocked_after_admin_freezes_booked_slot(user, admin, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    response = admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    assert response.status_code == 200

    detail = user.get(f"/api/bookings/{booking['id']}").json()
    assert detail["is_locked"] is True
    assert detail["can_edit"] is False

    edit = user.put(
        f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1)
    )
    assert edit.status_code == 423
    cancel = user.request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert cancel.status_code == 423


def test_admin_can_edit_a_manually_frozen_booking(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    response = admin.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, jira_number="JIRA-7777777"),
    )
    assert response.status_code == 200, response.text
    audit = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    assert any(
        e["override_reason"] == "Administrator override: manually frozen deployment slot."
        for e in audit
    )


def test_manual_freeze_blocks_document_upload_for_owner(user, admin, tenant, next_monday):
    import io

    booking = create_booking(user, tenant, next_monday, 1)
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    response = user.post(
        f"/api/bookings/{booking['id']}/attachments",
        data={"category": "TEST_RESULTS"},
        files={"file": ("plan.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert response.status_code == 423


def test_admin_can_unfreeze_and_owner_can_edit_again(user, admin, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": next_monday.isoformat(), "slot_number": 1},
    )
    unfrozen = admin.delete(f"/api/admin/slot-freezes/{next_monday.isoformat()}/1")
    assert unfrozen.status_code == 204, unfrozen.text

    detail = user.get(f"/api/bookings/{booking['id']}").json()
    assert detail["is_locked"] is False
    assert detail["can_edit"] is True
    assert user.put(
        f"/api/bookings/{booking['id']}", json=booking_payload(tenant, next_monday, 1)
    ).status_code == 200


def test_past_slot_cannot_be_frozen_or_unfrozen(admin):
    yesterday = date(2026, 9, 17)
    response = admin.post(
        "/api/admin/slot-freezes",
        json={"freeze_date": yesterday.isoformat(), "slot_number": 1},
    )
    assert response.status_code == 423
    assert "read-only" in response.json()["detail"]
