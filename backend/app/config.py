"""Application configuration, loaded from environment / .env file."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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

    @field_validator("storage_dir", "frontend_dist", mode="after")
    @classmethod
    def _anchor_to_project_root(cls, value: Path) -> Path:
        """Resolve a relative path against the project root, not the cwd.

        .env.example ships paths like ``./storage/deployments`` while the
        documented way to start the app is ``cd backend && python -m app``.
        Without this, uploads would land in ``backend/storage`` — somewhere the
        README's backup instructions never look.
        """
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


#: Every placeholder that ships in this repository, in the code defaults and in
#: .env.example. They are public knowledge, so production must never run with
#: one. Comparing against the field defaults alone is not enough: somebody who
#: copies .env.example gets a *different* placeholder that would slip through.
UNSAFE_VALUES = frozenset(
    {
        "change-me-in-production",
        "replace-with-a-long-random-string",
        "admin2024",
        "ChangeMe#2026",
    }
)


def _unsafe_configuration(settings: "Settings") -> list[str]:
    """Names the settings still holding a shipped placeholder."""
    problems: list[str] = []
    if settings.jwt_secret in UNSAFE_VALUES:
        problems.append("JWT_SECRET is still the example value")
    elif len(settings.jwt_secret) < 32:
        problems.append("JWT_SECRET is shorter than 32 characters")
    if settings.bootstrap_admin_password in UNSAFE_VALUES:
        problems.append("BOOTSTRAP_ADMIN_PASSWORD is still the example value")
    if any(value in settings.database_url for value in UNSAFE_VALUES):
        problems.append("DATABASE_URL still contains the example database password")
    return problems


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logger = logging.getLogger("scheduler")
    problems = _unsafe_configuration(settings)

    if settings.environment.lower() == "production":
        if problems:
            raise RuntimeError(
                "Refusing to start in production with example credentials:\n  - "
                + "\n  - ".join(problems)
                + "\nSet real values in .env before deploying."
            )
        if settings.database_url.startswith("sqlite"):
            logger.warning(
                "ENVIRONMENT=production but DATABASE_URL is SQLite; production runs on PostgreSQL."
            )
    elif problems:
        # Development stays frictionless: warn loudly, never block startup.
        logger.warning("Insecure configuration (fine for local POC use): %s", "; ".join(problems))

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        (PROJECT_ROOT / "storage").mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
