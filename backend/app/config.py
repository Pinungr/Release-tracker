"""Application configuration, loaded from environment / .env file."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Production Deployment Scheduler"
    environment: str = "development"

    database_url: str = Field(
        default="postgresql+psycopg://scheduler:change-me-in-production@localhost:5432/scheduler"
    )

    storage_dir: Path = PROJECT_ROOT / "storage" / "deployments"

    #: Compiled SPA served by this same process (`npm run build` output).
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    session_minutes: int = 480

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin2024"

    # Empty by default: the monolith serves the SPA from its own origin, and
    # the Vite dev server proxies /api, so no cross-origin request is ever
    # made. Only set this if you deliberately host the UI elsewhere.
    cors_origins: str = ""

    timezone: str = "Asia/Kolkata"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment.lower() == "production":
        if settings.jwt_secret.strip().lower() in {
            "change-me-in-production", "replace-with-a-long-random-string",
        } or len(settings.jwt_secret.strip()) < 32:
            raise RuntimeError("JWT_SECRET must be a unique secret of at least 32 characters in production; default placeholders are forbidden.")
        if settings.bootstrap_admin_password == Settings.model_fields["bootstrap_admin_password"].default:
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be set to a unique value in production.")
    elif len(settings.jwt_secret) < 32:
        logging.getLogger("scheduler").warning(
            "JWT_SECRET is shorter than 32 characters; set a longer secret before deploying."
        )
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        (PROJECT_ROOT / "storage").mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
