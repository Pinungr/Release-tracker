from __future__ import annotations

from sqlalchemy import select

from app.models import DeploymentBooking, Tenant, User


def test_user_registration_and_login_do_not_require_a_tenant(client):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "team_name": "Release Engineering",
            "contact_number": "+91 98765 43210",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "asha.nair@example.com"
    assert body["user"]["role"] == "TENANT_USER"

    login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha.nair@example.com", "password": "StrongPass!123"},
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    assert payload["token_type"] == "bearer"
    assert "tenant_name" not in payload["user"]


def test_admin_can_list_tenants_and_users(client, admin_headers):
    tenant = client.post(
        "/api/admin/tenants",
        headers=admin_headers,
        json={"name": "Platform Operations", "tenant_code": "PLATFORM-OPS"},
    )
    assert tenant.status_code == 201, tenant.text

    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
        },
    )
    assert registered.status_code == 201, registered.text

    tenants = client.get("/api/admin/tenants", headers=admin_headers)
    assert tenants.status_code == 200
    assert any(t["name"] == "Platform Operations" for t in tenants.json())

    users = client.get("/api/admin/users", headers=admin_headers)
    assert users.status_code == 200
    assert any(
        u["email"] == "asha.nair@example.com" and "tenant_name" not in u
        for u in users.json()
    )


def test_duplicate_username_or_email_is_rejected(client):
    first = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "tenant_name": "Platform Operations",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha2",
            "password": "StrongPass!123",
            "tenant_name": "Platform Operations",
        },
    )
    assert second.status_code == 409

    third = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha2.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "tenant_name": "Platform Operations",
        },
    )
    assert third.status_code == 409


def test_one_user_can_schedule_for_multiple_tenants_with_separate_quotas(client, admin_headers, db):
    tenant_a = client.post(
        "/api/admin/tenants",
        headers=admin_headers,
        json={"name": "Tenant A", "tenant_code": "TENANT-A"},
    )
    tenant_b = client.post(
        "/api/admin/tenants",
        headers=admin_headers,
        json={"name": "Tenant B", "tenant_code": "TENANT-B"},
    )
    assert tenant_a.status_code == 201, tenant_a.text
    assert tenant_b.status_code == 201, tenant_b.text

    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Pinaki User",
            "email": "pinaki@example.com",
            "username": "pinaki",
            "password": "StrongPass!123",
            "confirm_password": "StrongPass!123",
        },
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        json={"username_or_email": "pinaki", "password": "StrongPass!123"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def payload(tenant_id: int, slot: int, change: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "jira_change": change,
            "jira_task": f"TASK-{change}",
            "jira_url": f"https://jira.example.com/browse/{change}",
            "environment": "PROD",
            "technology": "Databricks",
            "requester_name": "Pinaki User",
            "requester_email": "pinaki@example.com",
            "verifier_name": "Verifier",
            "verifier_email": "verifier@example.com",
            "git_repository": "https://github.example.com/platform/release",
            "implementation_summary": "Deploy the release orchestration update.",
            "deployment_description": "Deploy the release orchestration update to production.",
            "deployment_date": "2099-01-06",
            "slot_number": slot,
            "booking_pin": "123456",
            "confirm_booking_pin": "123456",
        }

    tenant_a_id = tenant_a.json()["id"]
    tenant_b_id = tenant_b.json()["id"]
    assert client.post("/api/bookings", headers=user_headers, json=payload(tenant_a_id, 1, "CHG-A1")).status_code == 201
    assert client.post("/api/bookings", headers=user_headers, json=payload(tenant_a_id, 2, "CHG-A2")).status_code == 201
    assert client.post("/api/bookings", headers=user_headers, json=payload(tenant_b_id, 3, "CHG-B1")).status_code == 201

    blocked = client.post("/api/bookings", headers=user_headers, json=payload(tenant_a_id, 4, "CHG-A3"))
    assert blocked.status_code == 409, blocked.text
    assert "Tenant A" in blocked.text

    created = db.scalars(select(DeploymentBooking).where(DeploymentBooking.jira_change == "CHG-B1")).one()
    user = db.scalars(select(User).where(User.username == "pinaki")).one()
    assert created.tenant_id == tenant_b_id
    assert created.created_by_user_id == user.id


def test_user_can_change_password_and_admin_can_reset_password(client):
    reg = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "confirm_password": "StrongPass!123",
            "tenant_name": "Platform Operations",
        },
    )
    assert reg.status_code == 201, reg.text

    login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "StrongPass!123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    bad_change = client.post(
        "/api/auth/me/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "WrongPassword!123",
            "new_password": "NewPass!456",
            "confirm_new_password": "NewPass!456",
        },
    )
    assert bad_change.status_code == 401

    change = client.post(
        "/api/auth/me/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPass!123",
            "new_password": "NewPass!456",
            "confirm_new_password": "NewPass!456",
        },
    )
    assert change.status_code == 200, change.text

    old_again = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "StrongPass!123"},
    )
    assert old_again.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "NewPass!456"},
    )
    assert new_login.status_code == 200, new_login.text

    admin_reset = client.post(
        "/api/admin/users/1/reset-password",
        headers={"Authorization": f"Bearer {client.post('/api/admin/login', json={'username': 'testadmin', 'password': 'Sup3r-Secret-Pass'}).json()['access_token']}"},
        json={"new_password": "AdminReset!789", "confirm_new_password": "AdminReset!789"},
    )
    assert admin_reset.status_code == 200, admin_reset.text
    assert "password" not in admin_reset.text.lower()

    after_reset = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "NewPass!456"},
    )
    assert after_reset.status_code == 401

    successful_reset_login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "AdminReset!789"},
    )
    assert successful_reset_login.status_code == 200, successful_reset_login.text


def test_authenticated_user_can_update_own_booking_without_booking_pin(client):
    reg = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "confirm_password": "StrongPass!123",
            "tenant_name": "Platform Operations",
        },
    )
    assert reg.status_code == 201, reg.text

    user_login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha", "password": "StrongPass!123"},
    )
    assert user_login.status_code == 200, user_login.text
    token = user_login.json()["access_token"]

    booking = client.post(
        "/api/bookings",
        json={
            "tenant_name": "Platform Operations",
            "jira_change": "CHG1000001",
            "jira_task": "T1000",
            "jira_url": "https://jira.example.com/browse/CHG1000001",
            "environment": "PROD",
            "technology": "Databricks",
            "requester_name": "Asha Nair",
            "requester_email": "asha.nair@example.com",
            "requester_phone": "+91 98765 43210",
            "verifier_name": "Kalyani Sethuraman",
            "verifier_email": "kalyani.s@example.com",
            "git_repository": "https://github.example.com/platform/release",
            "implementation_summary": "Update release job orchestration.",
            "deployment_description": "Migrate the scheduler to the new orchestration flow.",
            "deployment_date": "2099-01-06",
            "slot_number": 1,
            "booking_pin": "123456",
            "confirm_booking_pin": "123456",
        },
    )
    assert booking.status_code == 201, booking.text
    booking_id = booking.json()["booking"]["id"]

    authorized_update = client.put(
        f"/api/bookings/{booking_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "deployment_date": "2099-01-06",
            "slot_number": 2,
            "requester_name": "Asha Nair",
            "requester_email": "asha.nair@example.com",
            "verifier_name": "Kalyani Sethuraman",
            "verifier_email": "kalyani.s@example.com",
            "git_repository": "https://github.example.com/platform/release",
            "implementation_summary": "Update release job orchestration.",
            "deployment_description": "Migrate the scheduler to the new orchestration flow.",
            "technology": "Databricks",
            "tenant_name": "Platform Operations",
            "jira_change": "CHG1000001",
            "jira_task": "T1000",
            "jira_url": "https://jira.example.com/browse/CHG1000001",
            "environment": "PROD",
        },
    )
    assert authorized_update.status_code == 200, authorized_update.text

    second_user_reg = client.post(
        "/api/auth/register",
        json={
            "full_name": "Rohan Shah",
            "email": "rohan.shah@example.com",
            "username": "rohan",
            "password": "StrongPass!456",
            "confirm_password": "StrongPass!456",
            "tenant_name": "Platform Operations",
        },
    )
    assert second_user_reg.status_code == 201, second_user_reg.text

    second_user_login = client.post(
        "/api/auth/login",
        json={"username_or_email": "rohan", "password": "StrongPass!456"},
    )
    assert second_user_login.status_code == 200, second_user_login.text
    second_token = second_user_login.json()["access_token"]

    unauthorized = client.put(
        f"/api/bookings/{booking_id}",
        headers={"Authorization": f"Bearer {second_token}"},
        json={
            "deployment_date": "2099-01-06",
            "slot_number": 3,
            "requester_name": "Another User",
            "requester_email": "another@example.com",
            "verifier_name": "Kalyani Sethuraman",
            "verifier_email": "kalyani.s@example.com",
            "git_repository": "https://github.example.com/platform/release",
            "implementation_summary": "Update release job orchestration.",
            "deployment_description": "Migrate the scheduler to the new orchestration flow.",
            "technology": "Databricks",
            "tenant_name": "Platform Operations",
            "jira_change": "CHG1000001",
            "jira_task": "T1000",
            "jira_url": "https://jira.example.com/browse/CHG1000001",
            "environment": "PROD",
        },
    )
    assert unauthorized.status_code in {401, 403}, unauthorized.text
