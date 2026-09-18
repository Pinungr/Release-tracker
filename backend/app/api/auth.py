"""Tenant authentication and tenant registration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tenant, User
from ..security import hash_secret, verify_secret
from ..security.tokens import create_user_token
from ..security.ratelimit import enforce

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest:
    pass


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
):
    enforce(request, "tenant-register", limit=20, window_seconds=300)

    full_name = str(payload.get("full_name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    tenant_name = str(payload.get("tenant_name", "")).strip()
    team_name = str(payload.get("team_name") or "").strip() or None
    contact_number = str(payload.get("contact_number") or "").strip() or None

    if not full_name or not email or not username or not password or not tenant_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing required registration fields.")

    if db.scalars(select(User).where((User.username == username) | (User.email == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.")

    tenant = db.scalars(select(Tenant).where(Tenant.name == tenant_name)).first()
    if tenant is None:
        tenant = Tenant(name=tenant_name, team_name=team_name, contact_email=email)
        db.add(tenant)
        db.flush()

    user = User(
        full_name=full_name,
        username=username,
        email=email,
        password_hash=hash_secret(password),
        tenant_id=tenant.id,
        team_name=team_name,
        contact_number=contact_number,
        role="TENANT",
    )
    db.add(user)
    db.flush()

    db.commit()
    return {
        "message": "User registered successfully.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "tenant_name": tenant.name,
            "role": user.role,
        },
        "tenant": {"id": tenant.id, "name": tenant.name, "team_name": tenant.team_name},
    }


@router.post("/login")
def login_user(request: Request, payload: dict, db: Session = Depends(get_db)):
    enforce(request, "tenant-login", limit=12, window_seconds=300)
    username_or_email = str(payload.get("username_or_email", "")).strip()
    password = str(payload.get("password", ""))

    user = db.scalars(
        select(User).where((User.username == username_or_email) | (User.email == username_or_email.lower()))
    ).first()

    if user is None or not user.is_active or not verify_secret(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username/email or password.")

    token, expires_in = create_user_token(user.id, user.username, user.tenant_id)
    user.last_login_at = __import__("app.utils.dates", fromlist=["now_utc"]).now_utc()
    db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "tenant_name": user.tenant.name if user.tenant else None,
            "role": user.role,
        },
    }
