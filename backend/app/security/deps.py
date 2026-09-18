"""Authentication / authorization dependencies.

The bearer token proves *who* is calling. It is never trusted for *what they
may do*: the role and active flag are re-read from the users table on every
request, so deactivating or demoting an account takes effect immediately
instead of when their token happens to expire.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from .tokens import decode_token

#: Revoked token ids (logout). Process-local by design: the app is a single
#: monolith, and tokens expire on their own anyway.
_revoked_jtis: set[str] = set()

ADMIN_ROLE = "ADMIN"


def revoke_token(payload: dict) -> None:
    jti = payload.get("jti")
    if jti:
        _revoked_jtis.add(jti)


@dataclass(frozen=True)
class UserPrincipal:
    """An authenticated person, with the role as currently stored."""

    user_id: int
    username: str
    email: str
    role: str
    payload: dict

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN_ROLE


#: Administrators are the same principal; the alias keeps router signatures
#: self-documenting where a route is admin-only.
AdminPrincipal = UserPrincipal


def _read_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def optional_user(request: Request, db: Session = Depends(get_db)) -> UserPrincipal | None:
    token = _read_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("jti") in _revoked_jtis:
        return None
    user_id = payload.get("user_id")
    if user_id is None:
        return None

    account = db.get(User, int(user_id))
    if account is None or not account.is_active:
        return None
    return UserPrincipal(
        user_id=account.id,
        username=account.username,
        email=account.email,
        role=account.role,
        payload=payload,
    )


def require_user(user: UserPrincipal | None = Depends(optional_user)) -> UserPrincipal:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def optional_admin(user: UserPrincipal | None = Depends(optional_user)) -> UserPrincipal | None:
    return user if user is not None and user.is_admin else None


def require_admin(user: UserPrincipal = Depends(require_user)) -> UserPrincipal:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required.",
        )
    return user
