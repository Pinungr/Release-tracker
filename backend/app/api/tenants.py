"""Tenant master lookup for authenticated scheduling clients."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tenant
from ..security import UserPrincipal, require_user

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/active", response_model=list[dict])
def list_active_tenants(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_user),
) -> list[dict]:
    tenants = db.scalars(
        select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name)
    ).all()
    return [
        {
            "id": tenant.id,
            "name": tenant.name,
            "tenant_code": tenant.tenant_code,
            "description": tenant.description,
        }
        for tenant in tenants
    ]
