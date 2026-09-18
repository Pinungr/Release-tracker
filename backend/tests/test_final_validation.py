"""The exact scenarios called out in the final validation pass.

These overlap with the focused suites on purpose: they assert the end-to-end
behaviour at the level the acceptance criteria describe, and they check the
stored rows rather than only the API responses.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import DeploymentBooking
from conftest import (
    authenticated,
    booking_payload,
    create_booking,
    create_tenant,
    emergency_payload,
    login,
    register,
)


def _third_user(anon):
    register(anon, "user3")
    return authenticated(login(anon, "user3"))


# --------------------------------------------------------------------------- #
# 6. Weekly limit is per tenant, across three different people
# --------------------------------------------------------------------------- #


def test_three_users_share_one_tenant_quota_then_succeed_on_another(
    anon, admin, user, other_user, next_monday
):
    tenant_x = create_tenant(admin, "Tenant X", "TEN-X")
    tenant_y = create_tenant(admin, "Tenant Y", "TEN-Y")
    user_c = _third_user(anon)

    try:
        # User A and User B fill Tenant X's quota.
        create_booking(user, tenant_x, next_monday, 1)
        create_booking(other_user, tenant_x, next_monday, 2)

        # User C is a different person but the quota belongs to the tenant.
        rejected = user_c.post("/api/bookings", json=booking_payload(tenant_x, next_monday, 3))
        assert rejected.status_code == 409
        assert "Weekly booking limit reached. Tenant X" in rejected.json()["detail"]

        # The same person succeeds immediately against a tenant with capacity.
        accepted = user_c.post("/api/bookings", json=booking_payload(tenant_y, next_monday, 3))
        assert accepted.status_code == 201
        assert accepted.json()["booking"]["tenant_id"] == tenant_y
    finally:
        user_c.close()


def test_admin_override_still_works_after_three_users_filled_the_quota(
    anon, admin, user, other_user, next_monday
):
    tenant_x = create_tenant(admin, "Tenant X", "TEN-X")
    create_booking(user, tenant_x, next_monday, 1)
    create_booking(other_user, tenant_x, next_monday, 2)

    override = admin.post(
        "/api/bookings",
        json=booking_payload(
            tenant_x,
            next_monday,
            3,
            override_weekly_limit=True,
            override_reason="Critical business deployment.",
        ),
    )
    assert override.status_code == 201
    audit = admin.get("/api/admin/audit").json()
    assert any(e["override_reason"] == "Critical business deployment." for e in audit)


# --------------------------------------------------------------------------- #
# 7. Ownership comes from the authenticated identity, not the request body
# --------------------------------------------------------------------------- #


def test_created_by_user_id_cannot_be_forged_in_the_payload(user, other_user, tenant, next_monday, db):
    """A client that injects created_by_user_id must not be believed."""
    victim = other_user.get("/api/auth/me").json()
    attacker = user.get("/api/auth/me").json()

    response = user.post(
        "/api/bookings",
        json=booking_payload(tenant, next_monday, 1, created_by_user_id=victim["id"]),
    )
    assert response.status_code == 201

    stored = db.scalars(
        select(DeploymentBooking).where(DeploymentBooking.id == response.json()["booking"]["id"])
    ).first()
    assert stored.created_by_user_id == attacker["id"], "ownership must come from the token"


def test_ownership_cannot_be_reassigned_by_editing(user, other_user, tenant, next_monday, db):
    booking = create_booking(user, tenant, next_monday, 1)
    victim = other_user.get("/api/auth/me").json()

    user.put(
        f"/api/bookings/{booking['id']}",
        json=booking_payload(tenant, next_monday, 1, created_by_user_id=victim["id"]),
    )
    stored = db.get(DeploymentBooking, booking["id"])
    assert stored.created_by_user_id != victim["id"]


def test_guessing_another_users_booking_id_is_refused(user, other_user, tenant, other_tenant, next_monday):
    mine = create_booking(user, tenant, next_monday, 1)
    theirs = create_booking(other_user, other_tenant, next_monday, 2)

    # Every route that touches somebody else's record refuses.
    assert user.get(f"/api/bookings/{theirs['id']}").status_code == 403
    assert user.get(f"/api/bookings/{theirs['id']}/attachments").status_code == 403
    assert (
        user.put(
            f"/api/bookings/{theirs['id']}", json=booking_payload(tenant, next_monday, 2)
        ).status_code
        == 403
    )
    assert user.request("DELETE", f"/api/bookings/{theirs['id']}", json={}).status_code == 403
    # ...and the caller's own record still works, so this is authorization and
    # not a blanket failure.
    assert user.get(f"/api/bookings/{mine['id']}").status_code == 200


def test_a_tenant_user_cannot_reach_admin_booking_routes(user, other_user, tenant, next_monday):
    theirs = create_booking(other_user, tenant, next_monday, 1)
    for method, path, body in [
        ("POST", f"/api/admin/bookings/{theirs['id']}/move", {"deployment_date": next_monday.isoformat(), "slot_number": 2}),
        ("POST", f"/api/admin/bookings/{theirs['id']}/reassign", {"tenant_id": tenant}),
        ("POST", f"/api/admin/bookings/{theirs['id']}/status", {"status": "COMPLETED"}),
        ("DELETE", f"/api/admin/bookings/{theirs['id']}", None),
    ]:
        response = user.request(method, path, json=body)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"


def test_admin_retains_global_access(admin, user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    assert admin.get(f"/api/bookings/{booking['id']}").status_code == 200
    assert admin.get(f"/api/bookings/{booking['id']}/attachments").status_code == 200
    assert (
        admin.put(
            f"/api/bookings/{booking['id']}",
            json=booking_payload(tenant, next_monday, 1, jira_change="CHG0555555"),
        ).status_code
        == 200
    )


# --------------------------------------------------------------------------- #
# 9. Three emergency changes on one date, verified in the database
# --------------------------------------------------------------------------- #


def test_three_emergency_changes_on_one_date_are_stored_correctly(
    admin, user, tenant, other_tenant, next_monday, db
):
    for index in range(3):
        response = admin.post(
            "/api/bookings",
            json=emergency_payload(
                tenant if index < 2 else other_tenant,
                next_monday,
                jira_change=f"CHG04440{index}",
            ),
        )
        assert response.status_code == 201, response.text

    stored = db.scalars(
        select(DeploymentBooking).where(
            DeploymentBooking.deployment_date == next_monday,
            DeploymentBooking.is_emergency.is_(True),
        )
    ).all()
    assert len(stored) == 3
    for row in stored:
        assert row.is_emergency is True
        assert row.slot_number is None, "an emergency change must not hold a slot"

    # Normal capacity is untouched: all four slots remain free and bookable.
    board = user.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    monday = board["days"][0]
    assert monday["regular_slots_total"] == 4
    assert monday["regular_slots_used"] == 0
    assert all(slot["bookable"] for slot in monday["slots"])
    assert len(monday["emergency_bookings"]) == 3

    # And a normal booking still succeeds alongside them.
    assert user.post("/api/bookings", json=booking_payload(tenant, next_monday, 1)).status_code == 201
