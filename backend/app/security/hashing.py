"""Password / PIN hashing.

bcrypt silently truncates inputs at 72 bytes, so every secret is pre-hashed
with SHA-256 and base64-encoded before hashing. Nothing here ever stores or
returns a plain-text password or PIN.
"""
from __future__ import annotations

import base64
import hashlib

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


