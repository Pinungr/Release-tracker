"""A promoted administrator must not be able to take over the installation.

Administrators manage tenant users. Acting on an account that is already an
ADMIN -- promoting, demoting, deactivating or resetting its password -- is
reserved for the single protected owner, and the owner account is never a
valid target for anybody.

Each test here is an escalation attempt that used to succeed.
"""
from __future__ import annotations

import pytest
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, authenticated, login, register


def _user_named(admin, username: str) -> dict:
    return next(u for u in admin.get("/api/admin/users").json() if u["username"] == username)


@pytest.fixture
def promoted_admin(anon, admin):
    """A second administrator, promoted by the owner. Not the owner."""
    register(anon, "mallory")
    target = _user_named(admin, "mallory")
    assert admin.patch(
        f"/api/admin/users/{target['id']}/role", json={"role": "ADMIN"}
    ).status_code == 200
    client = authenticated(login(anon, "mallory"))
    try:
        yield client
    finally:
        client.close()


def test_a_promoted_admin_is_not_the_owner(admin, promoted_admin):
    assert _user_named(admin, "mallory")["is_owner"] is False
    assert promoted_admin.get("/api/admin/users").status_code == 200


# --------------------------------------------------------------------------- #
# The owner account is untouchable
# --------------------------------------------------------------------------- #


def test_a_promoted_admin_cannot_reset_the_owners_password(anon, admin, promoted_admin):
    owner = _user_named(admin, ADMIN_USERNAME)
    response = promoted_admin.post(
        f"/api/admin/users/{owner['id']}/reset-password",
        json={"new_password": "Hijacked!123", "confirm_new_password": "Hijacked!123"},
    )
    assert response.status_code == 403

    # The owner's real credential still works, so no takeover occurred.
    assert (
        anon.post(
            "/api/auth/login",
            json={"username_or_email": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        ).status_code
        == 200
    )


def test_a_promoted_admin_cannot_demote_or_deactivate_the_owner(admin, promoted_admin):
    owner = _user_named(admin, ADMIN_USERNAME)
    assert promoted_admin.patch(
        f"/api/admin/users/{owner['id']}/role", json={"role": "TENANT_USER"}
    ).status_code == 403
    assert promoted_admin.patch(
        f"/api/admin/users/{owner['id']}/status", json={"is_active": False}
    ).status_code == 403

    still_owner = _user_named(admin, ADMIN_USERNAME)
    assert still_owner["role"] == "ADMIN"
    assert still_owner["is_active"] is True
    assert still_owner["is_owner"] is True


# --------------------------------------------------------------------------- #
# Peer administrators are protected from each other
# --------------------------------------------------------------------------- #


def test_a_promoted_admin_cannot_reset_a_peer_admins_password(anon, admin, promoted_admin):
    register(anon, "peer")
    peer = _user_named(admin, "peer")
    admin.patch(f"/api/admin/users/{peer['id']}/role", json={"role": "ADMIN"})

    response = promoted_admin.post(
        f"/api/admin/users/{peer['id']}/reset-password",
        json={"new_password": "Hijacked!123", "confirm_new_password": "Hijacked!123"},
    )
    assert response.status_code == 403
    assert "Only the owner" in response.json()["detail"]
    # The peer's own credential is untouched.
    assert login(anon, "peer")


def test_a_promoted_admin_cannot_demote_or_deactivate_a_peer_admin(anon, admin, promoted_admin):
    register(anon, "peer")
    peer = _user_named(admin, "peer")
    admin.patch(f"/api/admin/users/{peer['id']}/role", json={"role": "ADMIN"})

    assert promoted_admin.patch(
        f"/api/admin/users/{peer['id']}/role", json={"role": "TENANT_USER"}
    ).status_code == 403
    assert promoted_admin.patch(
        f"/api/admin/users/{peer['id']}/status", json={"is_active": False}
    ).status_code == 403
    assert _user_named(admin, "peer")["role"] == "ADMIN"


def test_a_promoted_admin_cannot_mint_new_administrators(anon, admin, promoted_admin):
    register(anon, "ally")
    ally = _user_named(admin, "ally")
    response = promoted_admin.patch(
        f"/api/admin/users/{ally['id']}/role", json={"role": "ADMIN"}
    )
    assert response.status_code == 403
    assert "Only the owner can promote" in response.json()["detail"]
    assert _user_named(admin, "ally")["role"] == "TENANT_USER"


def test_an_admin_cannot_act_on_their_own_account(admin, promoted_admin):
    me = _user_named(admin, "mallory")
    for path, body in (
        (f"/api/admin/users/{me['id']}/role", {"role": "TENANT_USER"}),
        (f"/api/admin/users/{me['id']}/status", {"is_active": False}),
    ):
        assert promoted_admin.patch(path, json=body).status_code == 403
    assert promoted_admin.post(
        f"/api/admin/users/{me['id']}/reset-password",
        json={"new_password": "Whatever!123", "confirm_new_password": "Whatever!123"},
    ).status_code == 403


# --------------------------------------------------------------------------- #
# What a promoted administrator *can* still do
# --------------------------------------------------------------------------- #


def test_a_promoted_admin_can_still_manage_tenant_users(anon, admin, promoted_admin):
    register(anon, "tenantuser")
    target = _user_named(admin, "tenantuser")

    assert promoted_admin.post(
        f"/api/admin/users/{target['id']}/reset-password",
        json={"new_password": "Replaced!123", "confirm_new_password": "Replaced!123"},
    ).status_code == 200
    assert promoted_admin.patch(
        f"/api/admin/users/{target['id']}/status", json={"is_active": False}
    ).status_code == 200
    assert _user_named(admin, "tenantuser")["is_active"] is False


def test_a_promoted_admin_keeps_normal_scheduling_privileges(promoted_admin, tenant, next_monday):
    from conftest import emergency_payload, post_booking

    assert post_booking(promoted_admin, emergency_payload(tenant, next_monday)).status_code == 201


def test_an_admin_changes_their_own_password_through_self_service(anon, promoted_admin):
    response = promoted_admin.post(
        "/api/auth/me/change-password",
        json={
            "current_password": "StrongPass!123",
            "new_password": "BrandNew!456",
            "confirm_new_password": "BrandNew!456",
        },
    )
    assert response.status_code == 200, response.text
    assert login(anon, "mallory", "BrandNew!456")


# --------------------------------------------------------------------------- #
# The installation always retains an owner
# --------------------------------------------------------------------------- #


def test_the_owner_flag_cannot_be_granted_through_the_api(admin, promoted_admin):
    """No endpoint accepts is_owner, so the tier cannot be escalated into."""
    mallory = _user_named(admin, "mallory")
    for client in (admin, promoted_admin):
        client.patch(f"/api/admin/users/{mallory['id']}/role", json={"role": "ADMIN", "is_owner": True})
        client.patch(f"/api/admin/users/{mallory['id']}/status", json={"is_active": True, "is_owner": True})
    assert _user_named(admin, "mallory")["is_owner"] is False


def test_an_owner_is_adopted_when_a_database_has_none(db, admin):
    """Covers an upgrade from before the owner tier existed."""
    from app.models import User
    from app.services import bootstrap

    for account in db.scalars(__import__("sqlalchemy").select(User)).all():
        account.is_owner = False
    db.commit()

    bootstrap.ensure_single_owner(db)
    owners = [u.username for u in db.scalars(__import__("sqlalchemy").select(User)).all() if u.is_owner]
    assert owners == [ADMIN_USERNAME]
