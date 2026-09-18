"""FastAPI dependencies for admin authentication / authorization."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .tokens import decode_admin_token

#: Revoked token ids (logout). Process-local by design: the app is a single
#: monolith, and tokens expire on their own anyway.
_revoked_jtis: set[str] = set()


def revoke_token(payload: dict) -> None:
    jti = payload.get("jti")
    if jti:
        _revoked_jtis.add(jti)


@dataclass(frozen=True)
class AdminPrincipal:
    username: str
    payload: dict


def _read_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def optional_admin(request: Request) -> AdminPrincipal | None:
    token = _read_token(request)
    if not token:
        return None
    payload = decode_admin_token(token)
    if not payload or payload.get("jti") in _revoked_jtis:
        return None
    return AdminPrincipal(username=str(payload.get("sub")), payload=payload)


def require_admin(admin: AdminPrincipal | None = Depends(optional_admin)) -> AdminPrincipal:
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin
