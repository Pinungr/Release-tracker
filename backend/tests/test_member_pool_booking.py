"""Member Pool users can schedule by choosing an active tenant explicitly."""
from __future__ import annotations

from app.models import AccessGroup, User
from app.services import group_service
from conftest import booking_payload, post_booking
from sqlalchemy import select


def test_member_pool_sees_all_active_tenants_and_can_book_one(user, admin, tenant, other_tenant, next_monday):
    options = user.get("/api/tenants/active")
    assert options.status_code == 200
    assert {item["id"] for item in options.json()} == {tenant, other_tenant}

    created = post_booking(user, booking_payload(other_tenant, next_monday, 1))
    assert created.status_code == 201, created.text
    assert created.json()["booking"]["tenant_id"] == other_tenant


def test_tenant_group_membership_restricts_the_member_pool_choice(
    user, admin, tenant, other_tenant, next_monday, db
):
    user_id = user.get("/api/auth/me").json()["id"]
    account = db.get(User, user_id)
    tenant_group = db.scalars(select(AccessGroup).where(AccessGroup.tenant_id == tenant)).first()
    assert account is not None and tenant_group is not None

    group_service.add_membership(db, tenant_group, account)
    db.commit()

    options = user.get("/api/tenants/active")
    assert options.status_code == 200
    assert [item["id"] for item in options.json()] == [tenant]

    denied = post_booking(user, booking_payload(other_tenant, next_monday, 1))
    assert denied.status_code == 403
    assert "tenant groups you belong to" in denied.json()["detail"]
