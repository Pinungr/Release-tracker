"""AI master switch, group grants, tenant grants and override precedence."""
from __future__ import annotations


def _group(admin, group_type: str, *, tenant_id: int | None = None) -> dict:
    groups = admin.get("/api/admin/groups").json()
    return next(
        group
        for group in groups
        if group["group_type"] == group_type
        and (tenant_id is None or group["tenant_id"] == tenant_id)
    )


def _user_id(client) -> int:
    return client.get("/api/auth/me").json()["id"]


def _join(admin, client, group: dict) -> None:
    response = admin.post(f"/api/admin/groups/{group['id']}/members/{_user_id(client)}")
    assert response.status_code == 200, response.text


def test_ai_is_centrally_off_by_default_even_for_override_user(admin, user):
    _join(admin, user, _group(admin, "AI_USERS"))

    settings = admin.get("/api/admin/ai-access")
    assert settings.status_code == 200
    assert settings.json()["ai_enabled"] is False

    denied = user.get("/api/assistant/count")
    assert denied.status_code == 403
    assert "disabled centrally" in denied.json()["detail"]


def test_ai_users_group_overrides_group_and_tenant_switches_only_when_master_on(admin, user):
    _join(admin, user, _group(admin, "AI_USERS"))
    response = admin.put(
        "/api/admin/ai-access",
        json={
            "ai_enabled": True,
            "management_enabled": False,
            "release_managers_enabled": False,
        },
    )
    assert response.status_code == 200, response.text

    allowed = user.get("/api/assistant/count")
    assert allowed.status_code == 200, allowed.text

    # Master OFF is authoritative and defeats even explicit AI Users membership.
    response = admin.put("/api/admin/ai-access", json={"ai_enabled": False})
    assert response.status_code == 200
    denied = user.get("/api/assistant/count")
    assert denied.status_code == 403
    assert "disabled centrally" in denied.json()["detail"]


def test_release_manager_group_can_be_enabled_independently(admin, user):
    _join(admin, user, _group(admin, "RELEASE_MANAGERS"))
    response = admin.put(
        "/api/admin/ai-access",
        json={"ai_enabled": True, "release_managers_enabled": True},
    )
    assert response.status_code == 200, response.text
    assert user.get("/api/assistant/count").status_code == 200

    response = admin.put("/api/admin/ai-access", json={"release_managers_enabled": False})
    assert response.status_code == 200
    assert user.get("/api/assistant/count").status_code == 403


def test_management_group_can_be_enabled_independently(admin, user):
    _join(admin, user, _group(admin, "MANAGEMENT"))
    response = admin.put(
        "/api/admin/ai-access",
        json={"ai_enabled": True, "management_enabled": True},
    )
    assert response.status_code == 200, response.text
    assert user.get("/api/assistant/count").status_code == 200


def test_tenant_ai_switch_grants_members_and_ai_users_does_not_remove_member_pool(admin, user, tenant):
    # A capability-only AI Users membership must not move an otherwise unassigned
    # user out of Member Pool.
    _join(admin, user, _group(admin, "AI_USERS"))
    groups_after_override = admin.get("/api/admin/groups").json()
    pool = next(group for group in groups_after_override if group["group_type"] == "MEMBER_POOL")
    pool_detail = admin.get(f"/api/admin/groups/{pool['id']}").json()
    assert any(member["id"] == _user_id(user) for member in pool_detail["members"])

    # Remove override, add normal tenant membership, then enable only that tenant.
    ai_group = _group(admin, "AI_USERS")
    removed = admin.delete(f"/api/admin/groups/{ai_group['id']}/members/{_user_id(user)}")
    assert removed.status_code == 200, removed.text
    _join(admin, user, _group(admin, "TENANT_SUBGROUP", tenant_id=tenant))

    response = admin.put(
        "/api/admin/ai-access",
        json={
            "ai_enabled": True,
            "tenants": [{"tenant_id": tenant, "enabled": True}],
        },
    )
    assert response.status_code == 200, response.text
    assert user.get("/api/assistant/count").status_code == 200

    response = admin.put(
        "/api/admin/ai-access",
        json={"tenants": [{"tenant_id": tenant, "enabled": False}]},
    )
    assert response.status_code == 200
    assert user.get("/api/assistant/count").status_code == 403


def test_group_page_ai_toggle_is_the_source_of_truth(admin, user):
    rm_group = _group(admin, "RELEASE_MANAGERS")
    _join(admin, user, rm_group)

    master = admin.put("/api/admin/ai-access", json={"ai_enabled": True})
    assert master.status_code == 200, master.text
    assert user.get("/api/assistant/count").status_code == 403

    enabled = admin.patch(
        f"/api/admin/groups/{rm_group['id']}/ai-access",
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["permissions"]["ai_enabled"] is True
    assert user.get("/api/assistant/count").status_code == 200

    disabled = admin.patch(
        f"/api/admin/groups/{rm_group['id']}/ai-access",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["permissions"]["ai_enabled"] is False
    assert user.get("/api/assistant/count").status_code == 403


def test_ai_users_membership_is_override_not_a_toggleable_group(admin):
    ai_group = _group(admin, "AI_USERS")
    response = admin.patch(
        f"/api/admin/groups/{ai_group['id']}/ai-access",
        json={"enabled": True},
    )
    assert response.status_code == 400


def test_owner_can_validate_ai_when_master_is_on(admin):
    enabled = admin.put("/api/admin/ai-access", json={"ai_enabled": True})
    assert enabled.status_code == 200, enabled.text

    access = admin.get("/api/assistant/access")
    assert access.status_code == 200, access.text
    assert access.json()["allowed"] is True
    assert access.json()["source"] == "OWNER"
