"""Sign-up, the single login, and role-based authorization.

There is exactly one users table and one login endpoint. A person's role in
that table decides what they may do; nothing else does.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import User
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, authenticated, login, register


# --------------------------------------------------------------------------- #
# Sign up
# --------------------------------------------------------------------------- #


def test_self_service_signup_creates_a_tenant_user(anon, db):
    created = register(anon, "pinaki")
    assert created["role"] == "TENANT_USER"

    account = db.scalars(select(User).where(User.username == "pinaki")).first()
    assert account is not None
    assert account.is_active is True
    assert account.full_name == "Pinaki Person"


def test_signup_never_grants_admin_even_when_asked(anon, db):
    response = anon.post(
        "/api/auth/register",
        json={
            "full_name": "Sneaky Person",
            "username": "sneaky",
            "email": "sneaky@example.com",
            "password": "StrongPass!123",
            "confirm_password": "StrongPass!123",
            "role": "ADMIN",
            "is_active": True,
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "TENANT_USER"

    account = db.scalars(select(User).where(User.username == "sneaky")).first()
    assert account.role == "TENANT_USER"


def test_signup_requires_matching_confirmation(anon):
    response = anon.post(
        "/api/auth/register",
        json={
            "full_name": "Mismatch Person",
            "username": "mismatch",
            "email": "mismatch@example.com",
            "password": "StrongPass!123",
            "confirm_password": "SomethingElse!9",
        },
    )
    assert response.status_code == 400
    assert "confirmation do not match" in response.json()["detail"]


def test_signup_rejects_duplicate_username_or_email(anon):
    register(anon, "pinaki")
    duplicate = anon.post(
        "/api/auth/register",
        json={
            "full_name": "Other Person",
            "username": "pinaki",
            "email": "different@example.com",
            "password": "StrongPass!123",
            "confirm_password": "StrongPass!123",
        },
    )
    assert duplicate.status_code == 409


def test_password_is_stored_hashed(anon, db):
    register(anon, "pinaki")
    account = db.scalars(select(User).where(User.username == "pinaki")).first()
    assert "StrongPass!123" not in account.password_hash
    assert account.password_hash.startswith("$2b$")


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


def test_login_works_with_username_or_email(anon):
    register(anon, "pinaki")
    by_username = anon.post(
        "/api/auth/login", json={"username_or_email": "pinaki", "password": "StrongPass!123"}
    )
    by_email = anon.post(
        "/api/auth/login",
        json={"username_or_email": "pinaki@example.com", "password": "StrongPass!123"},
    )
    assert by_username.status_code == by_email.status_code == 200
    assert by_username.json()["user"]["role"] == "TENANT_USER"


def test_admin_signs_in_through_the_same_login(anon, db):
    """The bootstrap administrator is an ordinary row in the users table."""
    response = anon.post(
        "/api/auth/login",
        json={"username_or_email": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "ADMIN"

    account = db.scalars(select(User).where(User.username == ADMIN_USERNAME)).first()
    assert account.role == "ADMIN"
    assert ADMIN_PASSWORD not in account.password_hash
    assert account.password_hash.startswith("$2b$")


def test_bootstrap_admin_is_not_reset_on_restart(anon, db):
    from app.services import bootstrap

    account = db.scalars(select(User).where(User.username == ADMIN_USERNAME)).first()
    original_hash = account.password_hash

    bootstrap.initialise()
    db.expire_all()
    account = db.scalars(select(User).where(User.username == ADMIN_USERNAME)).first()
    assert account.password_hash == original_hash
    assert db.scalar(select(User.id).where(User.username == ADMIN_USERNAME)) is not None


def test_login_rejects_bad_credentials(anon):
    register(anon, "pinaki")
    wrong_password = anon.post(
        "/api/auth/login", json={"username_or_email": "pinaki", "password": "nope"}
    )
    unknown_user = anon.post(
        "/api/auth/login", json={"username_or_email": "ghost", "password": "nope"}
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    # Same message: the endpoint cannot be used to enumerate accounts.
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


def test_login_is_rate_limited(anon):
    register(anon, "pinaki")
    statuses = [
        anon.post(
            "/api/auth/login", json={"username_or_email": "pinaki", "password": "wrong"}
        ).status_code
        for _ in range(15)
    ]
    assert 429 in statuses


def test_no_password_material_is_ever_returned(anon):
    body = anon.post(
        "/api/auth/login",
        json={"username_or_email": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    ).text
    assert "password" not in body.lower()
    assert ADMIN_PASSWORD not in body


# --------------------------------------------------------------------------- #
# Role enforcement
# --------------------------------------------------------------------------- #


def test_admin_routes_reject_anonymous_and_tenant_users(anon, user):
    for path in ("/api/admin/settings", "/api/admin/users", "/api/admin/audit", "/api/admin/tenants"):
        assert anon.get(path).status_code == 401, path
        assert user.get(path).status_code == 403, path


def test_garbage_token_is_rejected(anon):
    response = anon.get("/api/admin/settings", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


def test_scheduler_requires_authentication(anon, user):
    """The board is not public: everything sits behind the single login."""
    assert anon.get("/api/schedule").status_code == 401
    assert anon.get("/api/tenants/active").status_code == 401
    assert user.get("/api/schedule").status_code == 200


def test_logout_invalidates_the_token(admin):
    assert admin.get("/api/admin/me").status_code == 200
    assert admin.post("/api/admin/logout").status_code == 204
    assert admin.get("/api/admin/me").status_code == 401


def test_promotion_and_demotion_take_effect_on_the_next_request(anon, admin, user):
    """Authorization is read from the users table, never from the token."""
    assert user.get("/api/admin/settings").status_code == 403
    user_id = admin.get("/api/admin/users").json()
    target = next(u for u in user_id if u["username"] == "pinaki")

    promoted = admin.patch(f"/api/admin/users/{target['id']}/role", json={"role": "ADMIN"})
    assert promoted.status_code == 200
    # Same bearer token, new privileges: no re-login required.
    assert user.get("/api/admin/settings").status_code == 200

    demoted = admin.patch(f"/api/admin/users/{target['id']}/role", json={"role": "TENANT_USER"})
    assert demoted.status_code == 200
    assert user.get("/api/admin/settings").status_code == 403


def test_deactivation_takes_effect_immediately(admin, user):
    target = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "pinaki")
    assert user.get("/api/schedule").status_code == 200

    admin.patch(f"/api/admin/users/{target['id']}/status", json={"is_active": False})
    # The previously issued token is now worthless.
    assert user.get("/api/schedule").status_code == 401


def test_deactivated_user_cannot_log_in(anon, admin, user):
    target = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "pinaki")
    admin.patch(f"/api/admin/users/{target['id']}/status", json={"is_active": False})
    response = anon.post(
        "/api/auth/login", json={"username_or_email": "pinaki", "password": "StrongPass!123"}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


def test_user_can_read_own_profile(user):
    me = user.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "pinaki"
    assert me.json()["role"] == "TENANT_USER"
    assert "password_hash" not in me.text


def test_user_can_change_their_own_password(anon, user):
    changed = user.post(
        "/api/auth/me/change-password",
        json={
            "current_password": "StrongPass!123",
            "new_password": "BrandNew!456",
            "confirm_new_password": "BrandNew!456",
        },
    )
    assert changed.status_code == 200
    assert login(anon, "pinaki", "BrandNew!456")
    assert (
        anon.post(
            "/api/auth/login", json={"username_or_email": "pinaki", "password": "StrongPass!123"}
        ).status_code
        == 401
    )


def test_change_password_requires_the_current_one(user):
    response = user.post(
        "/api/auth/me/change-password",
        json={
            "current_password": "WrongPass!000",
            "new_password": "BrandNew!456",
            "confirm_new_password": "BrandNew!456",
        },
    )
    assert response.status_code == 401


def test_admin_password_reset_forces_a_change_and_never_exposes_the_hash(anon, admin, user):
    target = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "pinaki")
    # The admin list shows the must_change_password flag but never any
    # password material.
    listing = admin.get("/api/admin/users").text
    assert "password_hash" not in listing
    assert "$2b$" not in listing
    assert "StrongPass!123" not in listing

    reset = admin.post(
        f"/api/admin/users/{target['id']}/reset-password",
        json={"new_password": "ResetPass!789", "confirm_new_password": "ResetPass!789"},
    )
    assert reset.status_code == 200
    assert "ResetPass!789" not in reset.text

    token = login(anon, "pinaki", "ResetPass!789")
    with authenticated(token) as client:
        assert client.get("/api/auth/me").json()["must_change_password"] is True


def test_admin_password_reset_validates_the_confirmation(admin, user):
    target = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "pinaki")
    response = admin.post(
        f"/api/admin/users/{target['id']}/reset-password",
        json={"new_password": "ResetPass!789", "confirm_new_password": "Different!789"},
    )
    assert response.status_code == 400
