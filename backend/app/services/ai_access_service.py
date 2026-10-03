"""Central AI access policy for PDS.

The external MCP bearer key authenticates the connector/service. This module
answers a different question: whether a particular PDS user is allowed to use
AI at all.

Policy precedence:
1. Master AI switch OFF => nobody is allowed.
2. The protected Owner may use AI while the master switch is ON.
3. AI Users system-group membership => allowed while master is ON.
4. Membership in an AI-enabled Release Managers, Management, or tenant group
   => allowed.
5. Otherwise denied.

The master switch lives in ``application_settings``. Actual group grants live
in ``access_groups.permissions_json`` under ``ai_enabled`` so the Groups pages
are the single source of truth for access grants.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AccessGroup, ApplicationSetting, GroupMembership, GroupType, Tenant, User
from . import group_service

AI_ENABLED_KEY = "ai_enabled"
# Legacy keys are retained only so an existing POC database can be migrated
# without losing the administrator's previous RM/Management choices.
AI_MANAGEMENT_ENABLED_KEY = "ai_management_enabled"
AI_RELEASE_MANAGERS_ENABLED_KEY = "ai_release_managers_enabled"

AI_TOGGLE_GROUP_TYPES = {
    GroupType.RELEASE_MANAGERS.value,
    GroupType.MANAGEMENT.value,
    GroupType.TENANT_SUBGROUP.value,
}


@dataclass(frozen=True)
class AIAccessDecision:
    allowed: bool
    reason: str
    source: str | None = None


def _read_bool_setting(db: Session, key: str, *, default: bool = False) -> bool:
    row = db.get(ApplicationSetting, key)
    if row is None:
        return default
    return row.value.strip().lower() in {"1", "true", "yes", "on"}


def _set_bool_setting(db: Session, key: str, value: bool) -> None:
    row = db.get(ApplicationSetting, key)
    encoded = "true" if value else "false"
    if row is None:
        db.add(ApplicationSetting(key=key, value=encoded))
    else:
        row.value = encoded


def master_ai_enabled(db: Session) -> bool:
    return _read_bool_setting(db, AI_ENABLED_KEY, default=False)


def _permissions(group: AccessGroup) -> dict:
    return group_service.permissions(group)


def group_ai_enabled(group: AccessGroup) -> bool:
    return bool(_permissions(group).get("ai_enabled", False))


def can_toggle_group_ai(group: AccessGroup) -> bool:
    return group.group_type in AI_TOGGLE_GROUP_TYPES


def set_group_ai_enabled(db: Session, group: AccessGroup, enabled: bool) -> None:
    if not can_toggle_group_ai(group):
        raise ValueError(f"AI access cannot be configured for the {group.name} group.")
    permissions = _permissions(group)
    permissions["ai_enabled"] = bool(enabled)
    group.permissions_json = json.dumps(permissions, separators=(",", ":"), sort_keys=True)
    db.flush()


def _system_group(db: Session, group_type: str) -> AccessGroup | None:
    return db.scalars(
        select(AccessGroup).where(
            AccessGroup.group_type == group_type,
            AccessGroup.is_system.is_(True),
        )
    ).first()


def management_ai_enabled(db: Session) -> bool:
    group = _system_group(db, GroupType.MANAGEMENT.value)
    return bool(group and group.is_active and group_ai_enabled(group))


def release_manager_ai_enabled(db: Session) -> bool:
    group = _system_group(db, GroupType.RELEASE_MANAGERS.value)
    return bool(group and group.is_active and group_ai_enabled(group))


def tenant_ai_enabled(db: Session, tenant_id: int) -> bool:
    group = db.scalars(
        select(AccessGroup).where(
            AccessGroup.group_type == GroupType.TENANT_SUBGROUP.value,
            AccessGroup.tenant_id == tenant_id,
            AccessGroup.is_active.is_(True),
        )
    ).first()
    return bool(group and group_ai_enabled(group))


def set_tenant_ai_enabled(db: Session, tenant_id: int, enabled: bool) -> None:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError(f"Unknown tenant id {tenant_id}.")
    group = group_service.ensure_tenant_group(db, tenant)
    set_group_ai_enabled(db, group, enabled)


def migrate_legacy_group_settings(db: Session) -> None:
    """Move old RM/Management AI switches into their group permission docs.

    This runs safely on every startup. It writes a group flag only when that
    flag does not already exist, so a later change made on the Groups page is
    never overwritten by an old application setting.
    """
    groups = group_service.ensure_system_groups(db)
    migrations = (
        (GroupType.MANAGEMENT.value, AI_MANAGEMENT_ENABLED_KEY),
        (GroupType.RELEASE_MANAGERS.value, AI_RELEASE_MANAGERS_ENABLED_KEY),
    )
    for group_type, legacy_key in migrations:
        group = groups[group_type]
        permissions = _permissions(group)
        if "ai_enabled" in permissions:
            continue
        legacy = db.get(ApplicationSetting, legacy_key)
        if legacy is None:
            continue
        permissions["ai_enabled"] = _read_bool_setting(db, legacy_key)
        group.permissions_json = json.dumps(permissions, separators=(",", ":"), sort_keys=True)
    db.flush()


def is_ai_override_user(db: Session, user_id: int) -> bool:
    return db.scalar(
        select(GroupMembership.id)
        .join(AccessGroup, AccessGroup.id == GroupMembership.group_id)
        .where(
            GroupMembership.user_id == user_id,
            AccessGroup.group_type == GroupType.AI_USERS.value,
            AccessGroup.is_system.is_(True),
            AccessGroup.is_active.is_(True),
        )
        .limit(1)
    ) is not None


def evaluate_user(db: Session, user_id: int) -> AIAccessDecision:
    """Return the effective AI permission for an active PDS user."""
    if not master_ai_enabled(db):
        return AIAccessDecision(False, "AI is disabled centrally by the PDS administrator.", "master")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return AIAccessDecision(False, "The PDS user is inactive or does not exist.", "user")

    # The protected Owner must be able to validate the service after turning it
    # on. The master OFF switch above still remains authoritative.
    if user.is_owner:
        return AIAccessDecision(True, "Allowed for the PDS Owner.", "OWNER")

    if is_ai_override_user(db, user_id):
        return AIAccessDecision(True, "Allowed by AI Users override group.", "AI_USERS")

    groups = db.scalars(
        select(AccessGroup)
        .join(GroupMembership, GroupMembership.group_id == AccessGroup.id)
        .where(
            GroupMembership.user_id == user_id,
            AccessGroup.is_active.is_(True),
            AccessGroup.group_type.in_(AI_TOGGLE_GROUP_TYPES),
        )
        .order_by(AccessGroup.group_type, AccessGroup.name)
    ).all()
    for group in groups:
        if group_ai_enabled(group):
            return AIAccessDecision(True, f"Allowed by AI-enabled group {group.name}.", group.group_type)

    return AIAccessDecision(False, "This user is not in an AI-enabled group.", "policy")


def user_by_email(db: Session, email: str) -> User | None:
    normalized = email.strip().lower()
    if not normalized:
        return None
    return db.scalars(select(User).where(User.email.ilike(normalized))).first()


def user_by_username_or_email(db: Session, identity: str) -> User | None:
    normalized = identity.strip()
    if not normalized:
        return None
    return db.scalars(
        select(User).where(
            (User.email.ilike(normalized)) | (User.username.ilike(normalized))
        )
    ).first()


def access_snapshot(db: Session) -> dict:
    """Return safe admin-facing AI configuration (never includes secrets)."""
    groups = group_service.ensure_system_groups(db)
    group_service.sync_all_tenant_groups(db)
    migrate_legacy_group_settings(db)
    ai_group = groups[GroupType.AI_USERS.value]
    tenants = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    ai_members = list(
        db.scalars(select(GroupMembership.user_id).where(GroupMembership.group_id == ai_group.id)).all()
    )
    return {
        "ai_enabled": master_ai_enabled(db),
        # Retained for backwards-compatible API clients. These values now come
        # from the corresponding group permission, not separate switches.
        "management_enabled": management_ai_enabled(db),
        "release_managers_enabled": release_manager_ai_enabled(db),
        "ai_users_group": {
            "id": ai_group.id,
            "name": ai_group.name,
            "member_count": len(ai_members),
        },
        "tenants": [
            {
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "tenant_code": tenant.tenant_code,
                "is_active": tenant.is_active,
                "ai_enabled": tenant_ai_enabled(db, tenant.id),
            }
            for tenant in tenants
        ],
    }


def update_access(
    db: Session,
    *,
    ai_enabled: bool | None = None,
    management_enabled: bool | None = None,
    release_managers_enabled: bool | None = None,
    tenant_updates: list[tuple[int, bool]] | None = None,
) -> dict:
    """Update the master switch and support legacy API callers.

    New UI code only changes ``ai_enabled`` here; group grants are changed from
    the Groups pages. The other arguments are kept so older API clients/tests
    continue to map to the new group-backed storage correctly.
    """
    if ai_enabled is not None:
        _set_bool_setting(db, AI_ENABLED_KEY, ai_enabled)
    if management_enabled is not None:
        group = _system_group(db, GroupType.MANAGEMENT.value)
        if group is None:
            group = group_service.ensure_system_groups(db)[GroupType.MANAGEMENT.value]
        set_group_ai_enabled(db, group, management_enabled)
    if release_managers_enabled is not None:
        group = _system_group(db, GroupType.RELEASE_MANAGERS.value)
        if group is None:
            group = group_service.ensure_system_groups(db)[GroupType.RELEASE_MANAGERS.value]
        set_group_ai_enabled(db, group, release_managers_enabled)
    for tenant_id, enabled in tenant_updates or []:
        set_tenant_ai_enabled(db, tenant_id, enabled)
    db.flush()
    return access_snapshot(db)
