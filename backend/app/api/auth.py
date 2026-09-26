"""Person authentication and local account registration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import (
    hash_secret,
    require_authenticated_user,
    revoke_token,
    verify_secret,
)
from ..security.tokens import create_user_token
from ..security.ratelimit import enforce
from ..utils.dates import now_utc
from ..services import group_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    confirm_password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username_or_email: str = Field(min_length=1, max_length=180)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)
    confirm_new_password: str = Field(min_length=8, max_length=256)


def _group_payload(db: Session, user: User) -> list[dict]:
    return [
        {"id": g.id, "name": g.name, "group_type": g.group_type, "tenant_id": g.tenant_id}
        for g in group_service.user_groups(db, user.id)
    ]


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    enforce(request, "user-register", limit=20, window_seconds=300)

    if payload.password != payload.confirm_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password and confirmation do not match.")

    full_name = payload.full_name.strip()
    email = payload.email.strip().lower()
    username = payload.username.strip()

    if not full_name or not email or not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing required registration fields.")

    if db.scalars(select(User).where((User.username == username) | (User.email == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.")

    user = User(
        full_name=full_name,
        username=username,
        email=email,
        password_hash=hash_secret(payload.password),
        # A browser can never choose its own role: self-service sign-up
        # always lands on TENANT_USER, and only an admin can promote.
        role="TENANT_USER",
    )
    db.add(user)
    db.flush()
    group_service.reconcile_member_pool(db, user.id)

    db.commit()
    return {
        "message": "User registered successfully.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "groups": _group_payload(db, user),
        },
    }


@router.post("/login")
def login_user(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    enforce(request, "user-login", limit=12, window_seconds=300)
    username_or_email = payload.username_or_email.strip()
    password = payload.password

    user = db.scalars(
        select(User).where((User.username == username_or_email) | (User.email == username_or_email.lower()))
    ).first()
    if user is not None and user.is_active and verify_secret(password, user.password_hash):
        token, expires_in = create_user_token(user.id, user.username, user.email, user.token_version)
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
                "role": user.role,
                "groups": _group_payload(db, user),
                "is_owner": user.is_owner,
                "must_change_password": user.must_change_password,
            },
        }

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username/email or password.")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user=Depends(require_authenticated_user)) -> None:
    """Revoke the current local-auth token for either user role."""
    revoke_token(user.payload)


@router.post("/me/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
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
    db_user.must_change_password = False
    # Invalidate every JWT issued with the old password/security state.
    db_user.token_version += 1
    db.flush()
    token, expires_in = create_user_token(
        db_user.id, db_user.username, db_user.email, db_user.token_version
    )
    db.commit()
    return {
        "message": "Password updated successfully.",
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@router.get("/me")
def read_me(user=Depends(require_authenticated_user), db: Session = Depends(get_db)):
    account = db.get(User, user.user_id)
    if account is None or not account.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User account is unavailable.")
    return {
        "id": account.id,
        "full_name": account.full_name,
        "username": account.username,
        "email": account.email,
        "role": account.role,
        "groups": _group_payload(db, account),
        "is_owner": account.is_owner,
        "must_change_password": account.must_change_password,
    }
