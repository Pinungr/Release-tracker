"""Session tokens (JWT, HS256).

The token carries identity only. Authorization (``role``) is deliberately not
a claim: it is read from the users table on every request so there is exactly
one source of truth for what an account may do.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings


def create_user_token(
    user_id: int,
    username: str,
    email: str | None = None,
    token_version: int = 0,
) -> tuple[str, int]:
    expires_in = settings.session_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "user_id": user_id,
        "email": email or username,
        "token_version": int(token_version),
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
