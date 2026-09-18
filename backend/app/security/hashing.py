"""Password / PIN hashing.

bcrypt silently truncates inputs at 72 bytes, so every secret is pre-hashed
with SHA-256 and base64-encoded before hashing. Nothing here ever stores or
returns a plain-text password or PIN.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

import bcrypt


def _prepare(secret: str) -> bytes:
    return base64.b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def hash_secret(secret: str) -> str:
    return bcrypt.hashpw(_prepare(secret), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_secret(secret: str, hashed: str | None) -> bool:
    if not hashed or not secret:
        return False
    try:
        return bcrypt.checkpw(_prepare(secret), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def generate_manage_token() -> str:
    """Opaque, URL-safe token for the /booking/manage/<token> shortcut."""
    return secrets.token_urlsafe(32)


def hash_manage_token(token: str) -> str:
    """Tokens are high-entropy, so a fast keyed digest is sufficient and lets
    us look the booking up by hash in a single indexed query."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
