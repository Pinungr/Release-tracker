"""Tenant lookup scoped by group membership."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tenant
from ..security import UserPrincipal, require_user
from ..services import group_service

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/active", response_model=list[dict])
def list_active_tenants(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
) -> list[dict]:
    # Owner / Release Managers require the full list for administration and
    # overrides. Management is read-only but may see the organization-wide
    # schedule, so it also receives all tenant labels. Member Pool users are
    # intentionally unscoped: they may schedule for any active tenant, but the
    # booking form requires them to choose the tenant explicitly. Users who
    # belong to tenant subgroups continue to receive only those tenants.
    if user.is_admin or group_service.is_management(db, user.user_id):
        stmt = select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name)
    else:
        allowed = group_service.tenant_ids_for_user(db, user.user_id)
        if allowed:
            stmt = select(Tenant).where(Tenant.is_active.is_(True), Tenant.id.in_(allowed)).order_by(Tenant.name)
        elif group_service.is_member_pool(db, user.user_id):
            stmt = select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name)
        else:
            return []
    tenants = db.scalars(stmt).all()
    return [
        {
            "id": tenant.id,
            "name": tenant.name,
            "tenant_code": tenant.tenant_code,
            "description": tenant.description,
            "weekly_booking_limit": tenant.weekly_booking_limit,
        }
        for tenant in tenants
    ]
