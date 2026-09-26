"""Group membership and tenant-scope rules.

Member Pool is a system-managed holding group. A user belongs to it only while
it has no operational memberships. Tenant subgroups are 1:1 with tenant master
records so booking scope has one source of truth.
"""
from __future__ import annotations

import json
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AccessGroup, GroupMembership, GroupType, Tenant, User

SYSTEM_GROUPS = {
    GroupType.MEMBER_POOL.value: "Member Pool",
    GroupType.RELEASE_MANAGERS.value: "Release Managers",
    GroupType.TENANTS.value: "Tenants",
    GroupType.MANAGEMENT.value: "Management",
}


def system_group(db: Session, group_type: str) -> AccessGroup | None:
    return db.scalars(
        select(AccessGroup).where(
            AccessGroup.group_type == group_type,
            AccessGroup.is_system.is_(True),
        )
    ).first()


def ensure_system_groups(db: Session) -> dict[str, AccessGroup]:
    found: dict[str, AccessGroup] = {}
    for group_type, name in SYSTEM_GROUPS.items():
        group = system_group(db, group_type)
        if group is None:
            group = AccessGroup(name=name, group_type=group_type, is_system=True)
            db.add(group)
            db.flush()
        found[group_type] = group
    return found


def ensure_tenant_group(db: Session, tenant: Tenant) -> AccessGroup:
    groups = ensure_system_groups(db)
    existing = db.scalars(select(AccessGroup).where(AccessGroup.tenant_id == tenant.id)).first()
    if existing is not None:
        existing.name = tenant.name
        existing.is_active = tenant.is_active
        existing.parent_group_id = groups[GroupType.TENANTS.value].id
        return existing
    group = AccessGroup(
        name=tenant.name,
        group_type=GroupType.TENANT_SUBGROUP.value,
        parent_group_id=groups[GroupType.TENANTS.value].id,
        tenant_id=tenant.id,
        description=tenant.description,
        is_system=False,
        is_active=tenant.is_active,
    )
    db.add(group)
    db.flush()
    return group


def sync_all_tenant_groups(db: Session) -> None:
    for tenant in db.scalars(select(Tenant).order_by(Tenant.id)).all():
        ensure_tenant_group(db, tenant)
    db.flush()


def group_ids_for_user(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)).all())


def group_types_for_user(db: Session, user_id: int) -> set[str]:
    return set(db.scalars(
        select(AccessGroup.group_type)
        .join(GroupMembership, GroupMembership.group_id == AccessGroup.id)
        .where(GroupMembership.user_id == user_id, AccessGroup.is_active.is_(True))
    ).all())


def tenant_ids_for_user(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(
        select(AccessGroup.tenant_id)
        .join(GroupMembership, GroupMembership.group_id == AccessGroup.id)
        .where(
            GroupMembership.user_id == user_id,
            AccessGroup.group_type == GroupType.TENANT_SUBGROUP.value,
            AccessGroup.is_active.is_(True),
            AccessGroup.tenant_id.is_not(None),
        )
    ).all())


def is_release_manager(db: Session, user_id: int) -> bool:
    return GroupType.RELEASE_MANAGERS.value in group_types_for_user(db, user_id)


def search_release_managers(db: Session, query: str, *, limit: int = 10) -> list[User]:
    """Return active Release Manager group members matching a user-entered term.

    Release Manager membership is the source of truth; the legacy ``role`` field
    is intentionally not used here.
    """
    term = query.strip()
    if len(term) < 2:
        return []
    pattern = f"%{term}%"
    return list(db.scalars(
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .join(AccessGroup, AccessGroup.id == GroupMembership.group_id)
        .where(
            AccessGroup.group_type == GroupType.RELEASE_MANAGERS.value,
            AccessGroup.is_active.is_(True),
            User.is_active.is_(True),
            User.is_owner.is_(False),
            (User.full_name.ilike(pattern) | User.username.ilike(pattern) | User.email.ilike(pattern)),
        )
        .distinct()
        .order_by(User.full_name, User.username)
        .limit(limit)
    ).all())


def is_management(db: Session, user_id: int) -> bool:
    return GroupType.MANAGEMENT.value in group_types_for_user(db, user_id)


def is_member_pool(db: Session, user_id: int) -> bool:
    return GroupType.MEMBER_POOL.value in group_types_for_user(db, user_id)


def _operational_membership_count(db: Session, user_id: int) -> int:
    pool = system_group(db, GroupType.MEMBER_POOL.value)
    stmt = select(GroupMembership.id).where(GroupMembership.user_id == user_id)
    if pool is not None:
        stmt = stmt.where(GroupMembership.group_id != pool.id)
    return len(db.scalars(stmt).all())


def reconcile_member_pool(db: Session, user_id: int, *, added_by_user_id: int | None = None) -> None:
    groups = ensure_system_groups(db)
    pool = groups[GroupType.MEMBER_POOL.value]
    membership = db.scalars(select(GroupMembership).where(
        GroupMembership.group_id == pool.id,
        GroupMembership.user_id == user_id,
    )).first()
    operational = _operational_membership_count(db, user_id)
    if operational == 0 and membership is None:
        db.add(GroupMembership(group_id=pool.id, user_id=user_id, added_by_user_id=added_by_user_id))
    elif operational > 0 and membership is not None:
        db.delete(membership)
    db.flush()


def add_membership(db: Session, group: AccessGroup, user: User, *, actor_user_id: int | None = None) -> None:
    existing = db.scalars(select(GroupMembership).where(
        GroupMembership.group_id == group.id,
        GroupMembership.user_id == user.id,
    )).first()
    if existing is None:
        db.add(GroupMembership(group_id=group.id, user_id=user.id, added_by_user_id=actor_user_id))
        db.flush()
    reconcile_member_pool(db, user.id, added_by_user_id=actor_user_id)
    # Keep the legacy role synchronized until all old role checks are removed.
    if group.group_type == GroupType.RELEASE_MANAGERS.value and not user.is_owner:
        user.role = "ADMIN"


def remove_membership(db: Session, group: AccessGroup, user: User, *, actor_user_id: int | None = None) -> None:
    db.execute(delete(GroupMembership).where(
        GroupMembership.group_id == group.id,
        GroupMembership.user_id == user.id,
    ))
    if group.group_type == GroupType.RELEASE_MANAGERS.value and not user.is_owner:
        user.role = "TENANT_USER"
    db.flush()
    reconcile_member_pool(db, user.id, added_by_user_id=actor_user_id)


def user_groups(db: Session, user_id: int) -> list[AccessGroup]:
    return list(db.scalars(
        select(AccessGroup)
        .join(GroupMembership, GroupMembership.group_id == AccessGroup.id)
        .where(GroupMembership.user_id == user_id)
        .order_by(AccessGroup.group_type, AccessGroup.name)
    ).all())


def permissions(group: AccessGroup) -> dict:
    try:
        value = json.loads(group.permissions_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}
