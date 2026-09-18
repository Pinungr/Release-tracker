"""Session tokens (JWT, HS256)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings


def create_admin_token(username: str) -> tuple[str, int]:
    expires_in = settings.admin_session_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": "admin",
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def create_user_token(user_id: int, username: str, tenant_id: int | None = None) -> tuple[str, int]:
    expires_in = settings.admin_session_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": "tenant",
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def decode_admin_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("role") != "admin":
        return None
    return payload


def decode_user_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("role") != "tenant":
        return None
    return payload
