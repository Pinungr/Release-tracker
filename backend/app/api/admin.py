"""Administrator endpoints.

Every route requires an authenticated account whose stored role is ADMIN
(there is no separate administrator login), and every mutation is written
to the audit trail.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    ACTIVE_STATUSES,
    AccessGroup,
    AutomaticLockOverride,
    BookingAudit,
    BookingStatus,
    DailySlotCapacity,
    DeploymentBooking,
    DeploymentSlotConfiguration,
    GroupMembership,
    GroupType,
    Holiday,
    SlotFreeze,
    Tenant,
    User,
)
from ..schemas import (
    AssignUsersRequest,
    AuditEventOut,
    BookingDetail,
    DaySlotCapacityOut,
    DocumentTypeCreate,
    DocumentTypeOrder,
    DocumentTypeOut,
    DocumentTypeUpdate,
    HolidayIn,
    HolidayOut,
    LockOverrideOut,
    LockOverrideRequest,
    MoveBookingRequest,
    SettingsOut,
    SettingsUpdate,
    SlotConfigOut,
    SlotConfigReplace,
    SlotFreezeOut,
    SlotFreezeRequest,
    StatusUpdateRequest,
)
from ..security import (
    AdminPrincipal,
    UserPrincipal,
    hash_secret,
    require_admin,
    require_user,
)
from ..services import audit_service, booking_service, document_type_service, presenters, schedule_service, group_service, search_service
from ..services.booking_service import Actor, BusinessRuleError
from ..services.settings_service import get_app_settings, update_settings
from ..services.bootstrap import ensure_regular_slot_count
from ..utils.dates import now_utc, today_local
from .deps import get_booking

router = APIRouter(prefix="/admin", tags=["admin"])

#: Statuses an administrator may set directly.
SETTABLE_STATUSES = {BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.CANCELLED}


def _actor(admin: AdminPrincipal) -> Actor:
    return Actor(is_admin=True, admin_username=admin.username, user_id=admin.user_id)


def _tenant_weekly_limit(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weekly_booking_limit must be between 1 and 25, or blank for the global default.",
        ) from None
    if not 1 <= parsed <= 25:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weekly_booking_limit must be between 1 and 25, or blank for the global default.",
        )
    return parsed


def _is_owner(db: Session, admin: AdminPrincipal) -> bool:
    account = db.get(User, admin.user_id)
    return account is not None and account.is_owner


def _assert_may_manage(db: Session, target: User, admin: AdminPrincipal, action: str) -> None:
    """Gate every administrator action that targets another account.

    Without this, any administrator could reset a peer administrator's
    password or demote them, which is a full takeover of the installation by
    anyone who is promoted once. The rules are:

      * the owner account is never a valid target, for anybody;
      * an administrator cannot act on their own account here (self-service
        password change lives on /auth/me/change-password);
      * only the owner may act on an account whose role is ADMIN.

    Promotion to ADMIN is gated separately in ``update_user_role``, because
    its target is still a TENANT_USER at the time of the call.
    """
    if target.is_owner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"The owner account is protected and cannot be {action} by anyone. "
            "The owner manages their own credentials from their profile.",
        )
    if target.id == admin.user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You cannot have your own account {action}. Ask the owner.",
        )
    if target.role == "ADMIN" and not _is_owner(db, admin):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only the Owner can have a Release Manager account {action}.",
        )


def _assert_not_last_active_admin(db: Session, target: User, admin: AdminPrincipal) -> None:
    """Refuse a demotion/deactivation that would leave nobody able to administer."""
    if target.role != "ADMIN" or not target.is_active:
        return
    remaining = db.scalar(
        select(func.count(User.id)).where(
            User.role == "ADMIN",
            User.is_active.is_(True),
            User.id != target.id,
        )
    )
    if not remaining:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the only active administrator. Promote another account first.",
        )


@router.get("/tenants", response_model=list[dict])
def list_tenants(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    tenants = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "tenant_code": t.tenant_code,
            "description": t.description,
            "weekly_booking_limit": t.weekly_booking_limit,
            "is_active": t.is_active,
        }
        for t in tenants
    ]


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    name = str(payload.get("name", "")).strip()
    code = str(payload.get("tenant_code", "")).strip().upper()
    if not name or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tenant name and tenant code are required.")
    if db.scalars(select(Tenant).where((Tenant.name == name) | (Tenant.tenant_code == code))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant name or code already exists.")
    weekly_limit = _tenant_weekly_limit(payload.get("weekly_booking_limit"))
    tenant = Tenant(
        name=name,
        tenant_code=code,
        description=payload.get("description"),
        weekly_booking_limit=weekly_limit,
        is_active=True,
    )
    db.add(tenant)
    db.flush()
    group_service.ensure_tenant_group(db, tenant)
    audit_service.record(
        db,
        event_type="TENANT_CREATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values={
            "tenant_id": tenant.id,
            "name": tenant.name,
            "tenant_code": tenant.tenant_code,
            "weekly_booking_limit": tenant.weekly_booking_limit,
        },
    )
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.put("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    name = str(payload.get("name", tenant.name)).strip()
    code = str(payload.get("tenant_code", tenant.tenant_code or "")).strip().upper()
    duplicate = db.scalars(
        select(Tenant).where(
            Tenant.id != tenant_id,
            (Tenant.name == name) | (Tenant.tenant_code == code),
        )
    ).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant name or code already exists.")
    tenant.name = name
    tenant.tenant_code = code or None
    tenant.description = payload.get("description")
    if "weekly_booking_limit" in payload:
        tenant.weekly_booking_limit = _tenant_weekly_limit(payload.get("weekly_booking_limit"))
    group_service.ensure_tenant_group(db, tenant)
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.patch("/tenants/{tenant_id}/status")
def update_tenant_status(
    tenant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    if not isinstance(payload.get("is_active"), bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "is_active must be a boolean value.")
    tenant.is_active = payload["is_active"]
    group_service.ensure_tenant_group(db, tenant)
    db.commit()
    return {
        "id": tenant.id,
        "name": tenant.name,
        "tenant_code": tenant.tenant_code,
        "description": tenant.description,
        "weekly_booking_limit": tenant.weekly_booking_limit,
        "is_active": tenant.is_active,
    }


@router.get("/users", response_model=list[dict])
def list_users(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
    search: str | None = Query(default=None),
) -> list[dict]:
    stmt = select(User)
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            (User.username.ilike(q))
            | (User.email.ilike(q))
            | (User.full_name.ilike(q))
        )
    users = db.scalars(stmt.order_by(User.email)).all()
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_owner": u.is_owner,
            "is_active": u.is_active,
            "must_change_password": u.must_change_password,
            "created_at": u.created_at,
            "groups": [
                {"id": g.id, "name": g.name, "group_type": g.group_type, "tenant_id": g.tenant_id}
                for g in group_service.user_groups(db, u.id)
            ],
        }
        for u in users
    ]


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    _assert_may_manage(db, user, admin, "password reset")

    new_password = str(payload.get("new_password", ""))
    confirm_new_password = str(payload.get("confirm_new_password", ""))
    if new_password != confirm_new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password and confirmation do not match.")
    if len(new_password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 8 characters long.")

    user.password_hash = hash_secret(new_password)
    user.must_change_password = True
    # Immediately revoke all previously issued JWTs for this account. This
    # value is stored in the database, so the invalidation survives restarts.
    user.token_version += 1
    audit_service.record(
        db,
        event_type="PASSWORD_RESET_BY_ADMIN",
        actor_type="ADMIN",
        admin_username=admin.username,
        requester_email=user.email,
        old_values={"user_id": user.id, "username": user.username, "email": user.email},
        new_values={"user_id": user.id, "username": user.username, "email": user.email},
    )
    db.commit()
    return {"message": "Credential updated successfully.", "user_id": user.id, "username": user.username}


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    is_active = payload.get("is_active")
    if not isinstance(is_active, bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "is_active must be a boolean value.")
    _assert_may_manage(db, user, admin, "deactivated or reactivated")
    if not is_active:
        _assert_not_last_active_admin(db, user, admin)
    user.is_active = is_active
    audit_service.record(
        db,
        event_type="USER_STATUS_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        requester_email=user.email,
        old_values={"is_active": not is_active},
        new_values={"is_active": is_active},
    )
    db.commit()
    return {"message": "User status updated.", "user_id": user.id, "is_active": user.is_active}


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Compatibility endpoint: Release Manager access is now group membership."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    role = str(payload.get("role", "")).strip().upper()
    if role not in {"ADMIN", "TENANT_USER"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be ADMIN or TENANT_USER.")
    _assert_may_manage(db, user, admin, "promoted or demoted")
    rm = group_service.system_group(db, GroupType.RELEASE_MANAGERS.value)
    if rm is None:
        rm = group_service.ensure_system_groups(db)[GroupType.RELEASE_MANAGERS.value]
    if role == "ADMIN":
        if not _is_owner(db, admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Owner can grant Release Manager access.")
        group_service.add_membership(db, rm, user, actor_user_id=admin.user_id)
    else:
        _assert_not_last_active_admin(db, user, admin)
        group_service.remove_membership(db, rm, user, actor_user_id=admin.user_id)
    db.commit()
    return {"message": "Group membership updated.", "user_id": user.id, "role": user.role}


# --------------------------------------------------------------------------- #
# Group-based access control
# --------------------------------------------------------------------------- #

def _group_out(db: Session, group: AccessGroup, *, include_members: bool = False) -> dict:
    member_rows = []
    if include_members:
        users = db.scalars(
            select(User)
            .join(GroupMembership, GroupMembership.user_id == User.id)
            .where(GroupMembership.group_id == group.id)
            .order_by(User.full_name, User.username)
        ).all()
        member_rows = [
            {
                "id": u.id, "full_name": u.full_name, "username": u.username,
                "email": u.email, "is_active": u.is_active, "is_owner": u.is_owner,
            }
            for u in users
        ]
    count = db.scalar(select(func.count(GroupMembership.id)).where(GroupMembership.group_id == group.id)) or 0
    return {
        "id": group.id,
        "name": group.name,
        "group_type": group.group_type,
        "parent_group_id": group.parent_group_id,
        "tenant_id": group.tenant_id,
        "description": group.description,
        "permissions": group_service.permissions(group),
        "is_system": group.is_system,
        "is_active": group.is_active,
        "member_count": count,
        "members": member_rows,
    }


@router.get("/groups", response_model=list[dict])
def list_groups(
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    group_service.ensure_system_groups(db)
    group_service.sync_all_tenant_groups(db)
    db.commit()
    groups = db.scalars(
        select(AccessGroup).order_by(AccessGroup.parent_group_id.nulls_first(), AccessGroup.group_type, AccessGroup.name)
    ).all()
    return [_group_out(db, group) for group in groups]


@router.get("/release-managers/search", response_model=list[dict])
def search_release_managers(
    q: str = Query(min_length=2, max_length=100),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[dict]:
    """Type-ahead lookup for assignment; only RM group members are returned."""
    return [
        {
            "id": user.id,
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_owner": user.is_owner,
        }
        for user in group_service.search_release_managers(db, q, limit=10)
    ]


@router.get("/groups/{group_id}", response_model=dict)
def read_group(
    group_id: int,
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    group = db.get(AccessGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    result = _group_out(db, group, include_members=True)
    if search:
        term = search.strip().lower()
        result["members"] = [
            u for u in result["members"]
            if term in u["full_name"].lower() or term in u["username"].lower() or term in u["email"].lower()
        ]
    return result


@router.post("/groups", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_custom_group(
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Group name is required.")
    duplicate = db.scalars(select(AccessGroup).where(AccessGroup.name == name, AccessGroup.parent_group_id.is_(None))).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "A group with this name already exists.")
    import json
    permissions = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
    group = AccessGroup(
        name=name,
        group_type=GroupType.CUSTOM.value,
        description=str(payload.get("description", "")).strip() or None,
        permissions_json=json.dumps(permissions, separators=(",", ":")),
        is_system=False,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return _group_out(db, group)


@router.put("/groups/{group_id}", response_model=dict)
def update_group(
    group_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    group = db.get(AccessGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    import json
    if not group.is_system and group.group_type == GroupType.CUSTOM.value and "name" in payload:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Group name is required.")
        group.name = name
    if "description" in payload:
        group.description = str(payload.get("description", "")).strip() or None
    if "permissions" in payload and isinstance(payload.get("permissions"), dict):
        group.permissions_json = json.dumps(payload["permissions"], separators=(",", ":"))
    db.commit()
    return _group_out(db, group)


@router.post("/groups/{group_id}/members/{user_id}", response_model=dict)
def add_group_member(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    group = db.get(AccessGroup, group_id)
    user = db.get(User, user_id)
    if group is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group or user not found.")
    if group.group_type in {GroupType.MEMBER_POOL.value, GroupType.TENANTS.value}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This system group is managed automatically. Assign a working group or tenant subgroup instead.")
    if group.group_type == GroupType.RELEASE_MANAGERS.value and not _is_owner(db, admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Owner can grant Release Manager access.")
    group_service.add_membership(db, group, user, actor_user_id=admin.user_id)
    db.commit()
    return _group_out(db, group, include_members=True)


@router.delete("/groups/{group_id}/members/{user_id}", response_model=dict)
def remove_group_member(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> dict:
    group = db.get(AccessGroup, group_id)
    user = db.get(User, user_id)
    if group is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group or user not found.")
    if group.group_type == GroupType.MEMBER_POOL.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Member Pool is managed automatically.")
    if group.group_type == GroupType.RELEASE_MANAGERS.value:
        if not _is_owner(db, admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Owner can remove Release Manager access.")
        _assert_not_last_active_admin(db, user, admin)
    group_service.remove_membership(db, group, user, actor_user_id=admin.user_id)
    db.commit()
    return _group_out(db, group, include_members=True)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_group(
    group_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    group = db.get(AccessGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if group.is_system or group.group_type != GroupType.CUSTOM.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "System and tenant groups cannot be deleted here.")
    affected = list(db.scalars(select(GroupMembership.user_id).where(GroupMembership.group_id == group.id)).all())
    db.delete(group)
    db.flush()
    for uid in affected:
        group_service.reconcile_member_pool(db, uid, added_by_user_id=admin.user_id)
    db.commit()


# --------------------------------------------------------------------------- #
# Settings & slot configuration
# --------------------------------------------------------------------------- #


@router.get("/settings", response_model=SettingsOut)
def read_settings(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> SettingsOut:
    return SettingsOut(**presenters.settings_out(db))


@router.put("/settings", response_model=SettingsOut)
def write_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> SettingsOut:
    before = presenters.settings_out(db)
    changes = payload.model_dump(exclude_none=True)
    update_settings(db, changes)
    if "regular_slots_per_day" in changes:
        ensure_regular_slot_count(db, int(changes["regular_slots_per_day"]))
    after = presenters.settings_out(db)
    old, new = audit_service.diff(before, after)
    if old:
        audit_service.record(
            db,
            event_type="SETTINGS_UPDATED",
            actor_type="ADMIN",
            admin_username=admin.username,
            old_values=old,
            new_values=new,
        )
    db.commit()
    return SettingsOut(**after)


@router.get("/slots", response_model=list[SlotConfigOut])
def read_slots(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> list[SlotConfigOut]:
    rows = db.scalars(
        select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
    ).all()
    return [SlotConfigOut.model_validate(r) for r in rows]


@router.put("/slots", response_model=list[SlotConfigOut])
def replace_slots(
    payload: SlotConfigReplace,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[SlotConfigOut]:
    """Replaces the whole grid. Slot numbers that still hold active bookings
    cannot be removed, so the board can never reference a missing slot."""
    incoming = {s.slot_number for s in payload.slots}
    active = set(
        db.scalars(
            select(DeploymentBooking.slot_number).where(
                DeploymentBooking.status.in_(ACTIVE_STATUSES),
                DeploymentBooking.deployment_date >= today_local(),
            )
        ).all()
    )
    missing = sorted(active - incoming)
    if missing:
        raise BusinessRuleError(
            "Cannot remove slot "
            + ", ".join(str(m) for m in missing)
            + " while upcoming deployments are booked in it."
        )

    before = [
        SlotConfigOut.model_validate(r).model_dump(mode="json")
        for r in db.scalars(
            select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
        ).all()
    ]
    db.execute(delete(DeploymentSlotConfiguration))
    for slot in payload.slots:
        db.add(DeploymentSlotConfiguration(**slot.model_dump()))
    db.flush()
    rows = db.scalars(
        select(DeploymentSlotConfiguration).order_by(DeploymentSlotConfiguration.slot_number)
    ).all()
    audit_service.record(
        db,
        event_type="SLOT_CONFIG_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={"slots": before},
        new_values={"slots": [SlotConfigOut.model_validate(r).model_dump(mode="json") for r in rows]},
    )
    db.commit()
    return [SlotConfigOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- #
# Holidays
# --------------------------------------------------------------------------- #


@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[HolidayOut]:
    stmt = select(Holiday).order_by(Holiday.holiday_date)
    if year:
        stmt = stmt.where(
            Holiday.holiday_date >= date(year, 1, 1), Holiday.holiday_date <= date(year, 12, 31)
        )
    return [HolidayOut.model_validate(h) for h in db.scalars(stmt).all()]


@router.post("/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
def create_holiday(
    payload: HolidayIn,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> HolidayOut:
    holiday = Holiday(**payload.model_dump())
    db.add(holiday)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessRuleError(
            "A holiday already exists on that date.", status.HTTP_409_CONFLICT
        ) from None
    audit_service.record(
        db,
        event_type="HOLIDAY_CREATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values=payload.model_dump(mode="json"),
    )
    db.commit()
    return HolidayOut.model_validate(holiday)


@router.put("/holidays/{holiday_id}", response_model=HolidayOut)
def update_holiday(
    holiday_id: int,
    payload: HolidayIn,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> HolidayOut:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    before = HolidayOut.model_validate(holiday).model_dump(mode="json")
    for key, value in payload.model_dump().items():
        setattr(holiday, key, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessRuleError(
            "A holiday already exists on that date.", status.HTTP_409_CONFLICT
        ) from None
    audit_service.record(
        db,
        event_type="HOLIDAY_UPDATED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=before,
        new_values=HolidayOut.model_validate(holiday).model_dump(mode="json"),
    )
    db.commit()
    return HolidayOut.model_validate(holiday)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    audit_service.record(
        db,
        event_type="HOLIDAY_DELETED",
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values=HolidayOut.model_validate(holiday).model_dump(mode="json"),
    )
    db.delete(holiday)
    db.commit()


# --------------------------------------------------------------------------- #
# Per-date normal slot capacity
#
# The default count in Booking Rules applies to every deployment date. These
# routes let an administrator add or remove normal slots on one date without
# disturbing any other date. Emergency changes are a separate per-date queue
# and are never affected here.
# --------------------------------------------------------------------------- #

#: Matches the ``regular_slots_per_day`` ceiling in settings_service.LIMITS.
MAX_SLOTS_PER_DAY = 12


def _capacity_row(db: Session, day: date) -> DailySlotCapacity | None:
    return db.scalars(
        select(DailySlotCapacity).where(DailySlotCapacity.capacity_date == day)
    ).first()


def _day_capacity_out(db: Session, day: date) -> DaySlotCapacityOut:
    row = _capacity_row(db, day)
    return DaySlotCapacityOut(
        capacity_date=day,
        slot_count=schedule_service.resolve_day(db, day).configured_slot_count,
        custom_slot_count=row.slot_count if row else None,
        max_slot_count=MAX_SLOTS_PER_DAY,
    )


def _set_day_capacity(
    db: Session, day: date, slot_count: int, admin: AdminPrincipal, event_type: str
) -> DaySlotCapacityOut:
    row = _capacity_row(db, day)
    before = row.slot_count if row else None
    if row is None:
        row = DailySlotCapacity(capacity_date=day, slot_count=slot_count)
        db.add(row)
    else:
        row.slot_count = slot_count
    row.updated_by_user_id = admin.user_id
    # A slot can only be offered on a date once its configuration row exists.
    ensure_regular_slot_count(db, slot_count)
    db.flush()
    audit_service.record(
        db,
        event_type=event_type,
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={"capacity_date": day, "slot_count": before},
        new_values={"capacity_date": day, "slot_count": slot_count},
    )
    db.commit()
    return _day_capacity_out(db, day)




@router.post("/day-capacity/{day}/add-slot", response_model=DaySlotCapacityOut)
def add_day_slot(
    day: date,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> DaySlotCapacityOut:
    booking_service.assert_day_not_past(day)
    current = schedule_service.resolve_day(db, day).configured_slot_count
    if current >= MAX_SLOTS_PER_DAY:
        raise BusinessRuleError(
            f"A deployment date cannot carry more than {MAX_SLOTS_PER_DAY} normal slots."
        )
    return _set_day_capacity(db, day, current + 1, admin, "DAY_SLOT_ADDED")


@router.post("/day-capacity/{day}/remove-slot", response_model=DaySlotCapacityOut)
def remove_day_slot(
    day: date,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> DaySlotCapacityOut:
    booking_service.assert_day_not_past(day)
    current = schedule_service.resolve_day(db, day).configured_slot_count
    if current <= 0:
        raise BusinessRuleError("This deployment date has no normal slots left to remove.")
    highest_booked = db.scalar(
        select(func.max(DeploymentBooking.slot_number)).where(
            DeploymentBooking.deployment_date == day,
            DeploymentBooking.is_emergency.is_(False),
            DeploymentBooking.status.in_(ACTIVE_STATUSES),
        )
    )
    if highest_booked is not None and current <= highest_booked:
        raise BusinessRuleError(
            f"Slot {highest_booked} is booked on this date. Cancel or reschedule that "
            "booking before removing the slot.",
            status.HTTP_409_CONFLICT,
        )
    return _set_day_capacity(db, day, current - 1, admin, "DAY_SLOT_REMOVED")




# --------------------------------------------------------------------------- #
# Booking management
# --------------------------------------------------------------------------- #






@router.post("/bookings/{booking_id}/assign-users", response_model=BookingDetail)
def assign_booking_users(
    payload: AssignUsersRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    updated = booking_service.assign_users_to_booking(db, booking, payload.user_ids, _actor(admin))
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=True, user_id=admin.user_id)


@router.post("/bookings/{booking_id}/assign-self", response_model=BookingDetail)
def assign_booking_to_self(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    if not group_service.is_release_manager(db, admin.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Release Manager can assign a booking to themselves.")
    updated = booking_service.assign_users_to_booking(db, booking, [admin.user_id], _actor(admin))
    return presenters.booking_detail(db, updated, get_app_settings(db), is_admin=True, user_id=admin.user_id)


@router.post("/bookings/{booking_id}/move", response_model=BookingDetail)
def move_booking(
    payload: MoveBookingRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    from ..schemas import BookingUpdate
    from ..models import Technology

    if not booking.is_emergency and payload.slot_number is None:
        raise BusinessRuleError("A normal deployment slot is required when moving this booking.")

    update = BookingUpdate(
        tenant_id=booking.tenant_id,
        jira_number=booking.jira_number,
        jira_url=booking.jira_url,
        environment=booking.environment,
        technology=Technology(booking.technology),
        requester_name=booking.requester_name,
        requester_email=booking.requester_email,
        requester_phone=booking.requester_phone,
        verifier_name=booking.verifier_name,
        verifier_email=booking.verifier_email or None,
        git_repository=booking.git_repository,
        implementation_summary=booking.implementation_summary,
        deployment_description=booking.deployment_description,
        justification=booking.justification,
        impacted_region=booking.impacted_region,
        additional_comments=booking.additional_comments,
        emergency_reason=booking.emergency_reason,
        emergency_approval_reference=booking.emergency_approval_reference,
        emergency_approver=booking.emergency_approver,
        business_justification=booking.business_justification,
        deployment_date=payload.deployment_date,
        slot_number=payload.slot_number,
        manual_override=payload.manual_override,
        override_reason=payload.override_reason,
    )
    booking = booking_service.update_booking(db, booking, update, _actor(admin))
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True, user_id=admin.user_id)




@router.post("/bookings/{booking_id}/status", response_model=BookingDetail)
def set_status(
    payload: StatusUpdateRequest,
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    try:
        new_status = BookingStatus(payload.status)
    except ValueError:
        raise BusinessRuleError("Unknown booking status.") from None
    # LOCKED is derived from manual slot freezing, and the post-deployment
    # validation statuses are reserved for a future release, so neither can be
    # set here.
    if new_status not in SETTABLE_STATUSES:
        raise BusinessRuleError(
            "Only BOOKED, COMPLETED and CANCELLED can be set from the admin panel."
        )
    if new_status is not BookingStatus.COMPLETED:
        booking_service.assert_booking_mutable(db, booking, _actor(admin))
    if booking.status == BookingStatus.COMPLETED.value:
        raise BusinessRuleError("Use Reopen to restore a closed schedule to its previous status. Closed schedules cannot be cancelled.")
    if new_status is BookingStatus.BOOKED and booking.status != BookingStatus.BOOKED.value:
        raise BusinessRuleError("A started task cannot be reset to booked.")
    if new_status is BookingStatus.CANCELLED:
        booking_service.cancel_booking(db, booking, _actor(admin), payload.override_reason)
        return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True, user_id=admin.user_id)
    if new_status is BookingStatus.COMPLETED:
        if not booking_service.can_close_booking(booking, is_admin=True):
            raise BusinessRuleError("Only open or in-progress bookings can be completed/closed.")
        # Closure is independent of scheduling locks and starting work. Preserve
        # document readiness and explicitly audit any missing required evidence.
        readiness = booking_service.document_readiness(booking, document_type_service.active_types(db))
        if not readiness.complete and not (payload.override_reason or "").strip():
            payload.override_reason = ("Administrator closure with missing documents: " + ", ".join(readiness.missing_labels))[:500]
    old = booking.status
    booking.status = new_status.value
    if new_status is BookingStatus.CANCELLED and booking.cancelled_at is None:
        booking.cancelled_at = now_utc()
    db.flush()
    audit_service.record(
        db,
        event_type="BOOKING_STATUS_CHANGED",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        override_reason=payload.override_reason,
        old_values={"status": old},
        new_values={
            "status": booking.status,
            **({"documents_complete": readiness.complete, "missing_documents": readiness.missing_labels} if new_status is BookingStatus.COMPLETED else {}),
        },
    )
    db.commit()
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True, user_id=admin.user_id)


@router.post("/bookings/{booking_id}/reopen", response_model=BookingDetail)
def reopen_booking(
    booking: DeploymentBooking = Depends(get_booking),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> BookingDetail:
    """Admin/RM may reopen a closed record at any age; scheduling locks remain."""
    booking = booking_service.reopen_booking(db, booking, _actor(admin))
    return presenters.booking_detail(db, booking, get_app_settings(db), is_admin=True, user_id=admin.user_id)




def _booking_in_slot(db: Session, day: date, slot_number: int) -> DeploymentBooking | None:
    return db.scalars(
        select(DeploymentBooking).where(
            DeploymentBooking.deployment_date == day,
            DeploymentBooking.slot_number == slot_number,
            DeploymentBooking.is_emergency.is_(False),
            DeploymentBooking.status.in_(ACTIVE_STATUSES),
        )
    ).first()


@router.post("/slot-freezes", response_model=SlotFreezeOut)
def freeze_slot(
    payload: SlotFreezeRequest,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> SlotFreezeOut:
    booking_service.assert_day_not_past(payload.freeze_date)
    if schedule_service.find_slot(db, payload.freeze_date, payload.slot_number) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The selected deployment slot does not exist.")

    row = db.scalars(
        select(SlotFreeze).where(
            SlotFreeze.freeze_date == payload.freeze_date,
            SlotFreeze.slot_number == payload.slot_number,
        )
    ).first()
    if row is None:
        row = SlotFreeze(
            freeze_date=payload.freeze_date,
            slot_number=payload.slot_number,
            created_by_user_id=admin.user_id,
            note=payload.note or None,
        )
        db.add(row)
    else:
        row.note = payload.note or row.note
        row.created_by_user_id = admin.user_id

    db.flush()
    booking = _booking_in_slot(db, payload.freeze_date, payload.slot_number)
    audit_service.record(
        db,
        event_type="SLOT_MANUALLY_FROZEN",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        new_values={
            "deployment_date": payload.freeze_date,
            "slot_number": payload.slot_number,
            "note": row.note,
        },
    )
    db.commit()
    return SlotFreezeOut.model_validate(row)


@router.delete("/slot-freezes/{freeze_date}/{slot_number}", status_code=status.HTTP_204_NO_CONTENT)
def unfreeze_slot(
    freeze_date: date,
    slot_number: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    booking_service.assert_day_not_past(freeze_date)
    row = db.scalars(
        select(SlotFreeze).where(
            SlotFreeze.freeze_date == freeze_date, SlotFreeze.slot_number == slot_number
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This slot is not frozen.")
    booking = _booking_in_slot(db, freeze_date, slot_number)
    audit_service.record(
        db,
        event_type="SLOT_MANUALLY_UNFROZEN",
        booking=booking,
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={
            "deployment_date": freeze_date,
            "slot_number": slot_number,
            "note": row.note,
        },
    )
    db.delete(row)
    db.commit()


# --------------------------------------------------------------------------- #
# Automatic lock overrides (Unlock / Restore Lock)
# --------------------------------------------------------------------------- #


def _override_row(db: Session, day: date, slot_number: int | None) -> AutomaticLockOverride | None:
    stmt = select(AutomaticLockOverride).where(AutomaticLockOverride.override_date == day)
    stmt = stmt.where(
        AutomaticLockOverride.slot_number.is_(None) if slot_number is None
        else AutomaticLockOverride.slot_number == slot_number
    )
    return db.scalars(stmt).first()


def _slot_overrides_on(db: Session, day: date) -> list[AutomaticLockOverride]:
    return list(db.scalars(
        select(AutomaticLockOverride)
        .where(AutomaticLockOverride.override_date == day, AutomaticLockOverride.slot_number.is_not(None))
        .order_by(AutomaticLockOverride.slot_number)
    ).all())


def _override_audit_booking(db: Session, day: date, slot_number: int | None) -> DeploymentBooking | None:
    return _booking_in_slot(db, day, slot_number) if slot_number is not None else None


@router.post("/lock-overrides", response_model=LockOverrideOut, status_code=status.HTTP_201_CREATED)
def unlock_automatic_lock(
    payload: LockOverrideRequest,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> LockOverrideOut:
    """Unlock an automatically locked date (all slots) or one slot on it.

    Upcoming unlocks lift scheduling protection. Today and the previous seven
    days allow additional document uploads only; scheduling remains closed. Manual
    Freeze is untouched: a frozen slot stays frozen for tenant users and
    collaborators until it is unfrozen separately. A whole-date unlock absorbs
    any slot unlocks on that date, so one Restore Lock returns the whole date
    to the automatic lock.
    """
    day, slot_number = payload.override_date, payload.slot_number
    booking_service.assert_unlockable_date(day)
    if not booking_service.is_date_automatically_frozen(db, day):
        raise HTTPException(status.HTTP_409_CONFLICT, "This date is not automatically locked.")
    if slot_number is not None and schedule_service.find_slot(db, day, slot_number) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The selected deployment slot does not exist.")
    if _override_row(db, day, None) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This whole date is already unlocked.")
    if _override_row(db, day, slot_number) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This slot is already unlocked.")
    absorbed = _slot_overrides_on(db, day) if slot_number is None else []
    for existing in absorbed:
        db.delete(existing)
    row = AutomaticLockOverride(
        override_date=day,
        slot_number=slot_number,
        reason=(payload.reason or "").strip() or None,
        created_by_user_id=admin.user_id,
    )
    db.add(row)
    db.flush()
    audit_service.record(
        db,
        event_type="AUTOMATIC_LOCK_UNLOCKED",
        booking=_override_audit_booking(db, day, slot_number),
        actor_type="ADMIN",
        admin_username=admin.username,
        override_reason=row.reason,
        new_values={
            "deployment_date": day,
            "slot_number": slot_number if slot_number is not None else "All slots and emergency queue",
            "unlocked_by": admin.username,
            "manually_frozen": booking_service.is_slot_manually_frozen(db, day, slot_number),
            "scope": "ADDITIONAL_UPLOADS" if booking_service.is_current_or_past_deployment(day) else "SCHEDULING",
            **({"replaced_slot_unlocks": [o.slot_number for o in absorbed]} if absorbed else {}),
        },
    )
    db.commit()
    return LockOverrideOut.model_validate(row)


@router.delete("/lock-overrides/{override_date}", status_code=status.HTTP_204_NO_CONTENT)
def restore_automatic_lock(
    override_date: date,
    slot_number: int | None = Query(default=None, ge=1, le=50),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> None:
    """Remove an unlock so the date/slot follows the automatic lock again.

    Without ``slot_number`` every unlock on the date is removed, including any
    slot-level ones, so no slot is left open after restoring the date.
    """
    # An expired follow-up unlock can still be revoked; it never reopens scheduling.
    row = _override_row(db, override_date, slot_number)
    slot_rows = _slot_overrides_on(db, override_date) if slot_number is None else []
    if row is None and not slot_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no unlock to restore here.")
    audit_service.record(
        db,
        event_type="AUTOMATIC_LOCK_RESTORED",
        booking=_override_audit_booking(db, override_date, slot_number),
        actor_type="ADMIN",
        admin_username=admin.username,
        old_values={
            "deployment_date": override_date,
            "slot_number": slot_number if slot_number is not None else "All slots and emergency queue",
            "unlock_reason": row.reason if row is not None else None,
            **({"slot_unlocks_removed": [o.slot_number for o in slot_rows]} if slot_rows else {}),
        },
        new_values={"restored_by": admin.username},
    )
    for stale in ([row] if row is not None else []) + slot_rows:
        db.delete(stale)
    db.commit()


# --------------------------------------------------------------------------- #
# Document upload configuration
# --------------------------------------------------------------------------- #


def _document_types_out(db: Session) -> list[DocumentTypeOut]:
    counts = document_type_service.usage_counts(db)
    multi = document_type_service.multi_file_schedule_counts(db)
    return [
        DocumentTypeOut.model_validate(t).model_copy(
            update={"file_count": counts.get(t.key, 0), "multi_file_schedules": multi.get(t.key, 0)}
        )
        for t in document_type_service.all_types(db)
    ]


def _document_type(db: Session, type_id: int):
    from ..models import DocumentType

    doc_type = db.get(DocumentType, type_id)
    if doc_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document type not found.")
    return doc_type


@router.get("/document-types", response_model=list[DocumentTypeOut])
def list_document_types(
    db: Session = Depends(get_db), admin: AdminPrincipal = Depends(require_admin)
) -> list[DocumentTypeOut]:
    return _document_types_out(db)


@router.post("/document-types", response_model=list[DocumentTypeOut], status_code=status.HTTP_201_CREATED)
def create_document_type(
    payload: DocumentTypeCreate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[DocumentTypeOut]:
    document_type_service.create(
        db,
        label=payload.label,
        description=payload.description,
        is_required=payload.is_required,
        allow_multiple=payload.allow_multiple,
        is_active=payload.is_active,
        key=payload.key,
        user_id=admin.user_id,
        admin_username=admin.username,
    )
    db.commit()
    return _document_types_out(db)


@router.put("/document-types/order", response_model=list[DocumentTypeOut])
def reorder_document_types(
    payload: DocumentTypeOrder,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[DocumentTypeOut]:
    document_type_service.reorder(db, payload.ids, user_id=admin.user_id, admin_username=admin.username)
    db.commit()
    return _document_types_out(db)


@router.put("/document-types/{type_id}", response_model=list[DocumentTypeOut])
def update_document_type(
    type_id: int,
    payload: DocumentTypeUpdate,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[DocumentTypeOut]:
    document_type_service.update(
        db,
        _document_type(db, type_id),
        payload.model_dump(exclude_unset=True),
        user_id=admin.user_id,
        admin_username=admin.username,
    )
    db.commit()
    return _document_types_out(db)


@router.delete("/document-types/{type_id}", response_model=list[DocumentTypeOut])
def delete_document_type(
    type_id: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
) -> list[DocumentTypeOut]:
    document_type_service.delete(db, _document_type(db, type_id), admin_username=admin.username)
    db.commit()
    return _document_types_out(db)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


@router.get("/audit", response_model=list[AuditEventOut])
def read_audit(
    booking_id: int | None = None,
    q: str | None = Query(default=None, max_length=120),
    event_type: str | None = Query(default=None, max_length=48),
    actor_type: str | None = Query(default=None, pattern="^(USER|ADMIN|SYSTEM)$"),
    tenant_id: int | None = Query(default=None, ge=1),
    days: int | None = Query(default=None, ge=1, le=search_service.MAX_DAYS),
    date_from: date | None = None,
    date_to: date | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    viewer: UserPrincipal = Depends(require_user),
) -> list[AuditEventOut]:
    # Central Audit is read-only for Management and also available to the
    # Owner / Release Managers. No other admin routes are opened to Management.
    if not viewer.is_admin and not group_service.is_management(db, viewer.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Central Audit access is restricted to Release Management and Management users.")
    # Discussion has its own UI; keep the audit trail focused on operational/admin changes.
    stmt = select(BookingAudit).where(
        BookingAudit.event_type.not_in(["COMMENT_ADDED", "INTERNAL_NOTE_ADDED"])
    )
    if booking_id:
        stmt = stmt.where(BookingAudit.booking_id == booking_id)
    if tenant_id is not None:
        stmt = stmt.where(BookingAudit.tenant_id == tenant_id)
    window_start, window_end = search_service.date_window(days, date_from, date_to).utc_bounds()
    if window_start is not None:
        stmt = stmt.where(BookingAudit.created_at >= window_start)
    if window_end is not None:
        stmt = stmt.where(BookingAudit.created_at < window_end)
    if before_id is not None:
        cursor = db.get(BookingAudit, before_id)
        if cursor is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid audit pagination cursor.")
        # Compare the stored values directly. SQLite server defaults omit
        # fractional seconds, while bound Python datetimes include them.
        cursor_time = select(BookingAudit.created_at).where(BookingAudit.id == cursor.id).scalar_subquery()
        stmt = stmt.where(or_(
            BookingAudit.created_at < cursor_time,
            (BookingAudit.created_at == cursor_time) & (BookingAudit.id < cursor.id),
        ))
    if event_type:
        stmt = stmt.where(BookingAudit.event_type == event_type.strip().upper())
    if actor_type:
        normalized_actor = actor_type.strip().upper()
        if normalized_actor == 'USER':
            stmt = stmt.where(BookingAudit.actor_type.in_(['USER', 'TENANT_USER']))
        else:
            stmt = stmt.where(BookingAudit.actor_type == normalized_actor)
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(or_(
            BookingAudit.booking_reference.icontains(term, autoescape=True),
            BookingAudit.event_type.icontains(term, autoescape=True),
            BookingAudit.requester_email.icontains(term, autoescape=True),
            BookingAudit.admin_username.icontains(term, autoescape=True),
            BookingAudit.old_values.icontains(term, autoescape=True),
            BookingAudit.new_values.icontains(term, autoescape=True),
        ))
    stmt = stmt.options(selectinload(BookingAudit.tenant)).order_by(BookingAudit.created_at.desc(), BookingAudit.id.desc()).limit(limit)
    return [presenters.audit_event_out(e) for e in db.scalars(stmt).all()]
