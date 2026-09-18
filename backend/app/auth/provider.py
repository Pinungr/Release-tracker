"""Authentication provider abstraction.

This keeps the local-first implementation compatible with future LDAP or
Active Directory integrations without redesigning the service layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.security import verify_secret


class AuthProvider(ABC):
    """Common provider contract for authenticating application users."""

    @abstractmethod
    def authenticate(self, username: str, password: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def user_display_name(self, username: str) -> str | None:
        raise NotImplementedError


class LocalAuthProvider(AuthProvider):
    """The initial production-ready provider for local app users."""

    def __init__(self, user_lookup):
        self._user_lookup = user_lookup

    def authenticate(self, username: str, password: str) -> bool:
        user = self._user_lookup(username)
        if user is None or not getattr(user, "is_active", True):
            return False
        return bool(user.password_hash and verify_secret(password, user.password_hash))

    def user_display_name(self, username: str) -> str | None:
        user = self._user_lookup(username)
        if user is None:
            return None
        return getattr(user, "display_name", username)
