"""Tenant authentication and tenant registration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, Tenant, User
from ..security import create_admin_token, hash_secret, require_user, verify_secret
from ..security.tokens import create_user_token
from ..security.ratelimit import enforce
from ..utils.dates import now_utc

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    confirm_password: str | None = Field(default=None, min_length=8, max_length=256)
    tenant_name: str = Field(min_length=1, max_length=120)
    team_name: str | None = Field(default=None, max_length=120)
    contact_number: str | None = Field(default=None, max_length=40)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username_or_email: str = Field(min_length=1, max_length=180)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)
    confirm_new_password: str = Field(min_length=8, max_length=256)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    enforce(request, "tenant-register", limit=20, window_seconds=300)

    if payload.confirm_password is not None and payload.password != payload.confirm_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password and confirmation do not match.")

    full_name = payload.full_name.strip()
    email = payload.email.strip().lower()
    username = payload.username.strip()
    tenant_name = payload.tenant_name.strip()
    team_name = (payload.team_name or "").strip() or None
    contact_number = (payload.contact_number or "").strip() or None

    if not full_name or not email or not username or not tenant_name:
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
        password_hash=hash_secret(payload.password),
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
def login_user(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    enforce(request, "tenant-login", limit=12, window_seconds=300)
    username_or_email = payload.username_or_email.strip()
    password = payload.password

    user = db.scalars(
        select(User).where((User.username == username_or_email) | (User.email == username_or_email.lower()))
    ).first()
    if user is not None and user.is_active and verify_secret(password, user.password_hash):
        token, expires_in = create_user_token(user.id, user.username, user.tenant_id, user.email)
        user.last_login_at = now_utc()
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

    admin = db.scalars(select(AdminUser).where(AdminUser.username == username_or_email)).first()
    if admin is not None and admin.is_active and verify_secret(password, admin.password_hash):
        token, expires_in = create_admin_token(admin.username)
        admin.last_login_at = now_utc()
        db.commit()
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": {
                "id": admin.id,
                "full_name": admin.display_name,
                "username": admin.username,
                "email": None,
                "tenant_name": None,
                "role": "ADMIN",
            },
        }

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username/email or password.")


@router.post("/me/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    enforce(request, "tenant-change-password", limit=10, window_seconds=300)
    db_user = db.get(User, user.user_id)
    if db_user is None or not db_user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User account is unavailable.")
    if not verify_secret(payload.current_password, db_user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect.")
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password and confirmation do not match.")
    db_user.password_hash = hash_secret(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully."}
