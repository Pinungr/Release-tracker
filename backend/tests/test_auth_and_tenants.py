from __future__ import annotations

from app.models import Tenant, TenantUser


def test_tenant_user_registration_and_login(client):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "tenant_name": "Platform Operations",
            "team_name": "Release Engineering",
            "contact_number": "+91 98765 43210",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "asha.nair@example.com"
    assert body["tenant"]["name"] == "Platform Operations"

    login = client.post(
        "/api/auth/login",
        json={"username_or_email": "asha.nair@example.com", "password": "StrongPass!123"},
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["tenant_name"] == "Platform Operations"


def test_admin_can_list_tenants_and_users(client, admin_headers):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Asha Nair",
            "email": "asha.nair@example.com",
            "username": "asha",
            "password": "StrongPass!123",
            "tenant_name": "Platform Operations",
            "team_name": "Release Engineering",
            "contact_number": "+91 98765 43210",
        },
    )

    tenants = client.get("/api/admin/tenants", headers=admin_headers)
    assert tenants.status_code == 200
    assert any(t["name"] == "Platform Operations" for t in tenants.json())

    users = client.get("/api/admin/users", headers=admin_headers)
    assert users.status_code == 200
    assert any(u["email"] == "asha.nair@example.com" for u in users.json())


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
