"""Database schema migration runner.

This project is still at its initial development stage, so the migration
history is intentionally squashed into one clean initial revision. Application
startup simply upgrades a fresh database to the current Alembic head.

If the schema changes after real data starts being retained, add a new Alembic
revision instead of rewriting the initial revision.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def upgrade_database() -> None:
    """Upgrade the configured database to the latest schema."""
    command.upgrade(_config(), "head")
