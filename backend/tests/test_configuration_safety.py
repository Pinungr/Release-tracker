"""Production must refuse to start on the credentials this repo ships.

Every placeholder in the code defaults *and* in .env.example is public
knowledge. Checking only the field defaults would miss the most likely
mistake: copying .env.example and flipping ENVIRONMENT to production.
"""
from __future__ import annotations

import pytest

from app.config import Settings, UNSAFE_VALUES, _unsafe_configuration

REAL_SECRET = "P9-nOtAnExampLe-secret-value-with-enough-length-1234"


def _settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "jwt_secret": REAL_SECRET,
        "bootstrap_admin_password": "Real!Pass2026",
        "database_url": "postgresql+psycopg://scheduler:s3cret@postgres:5432/scheduler",
    }
    base.update(overrides)
    return Settings(**base)


def test_shipped_placeholders_are_all_listed_as_unsafe():
    """Anything this repository ships as an example must be in the set."""
    for placeholder in (
        "change-me-in-production",
        "replace-with-a-long-random-string",
        "admin2024",
    ):
        assert placeholder in UNSAFE_VALUES


def test_real_values_report_no_problems():
    assert _unsafe_configuration(_settings()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"jwt_secret": "replace-with-a-long-random-string"}, "JWT_SECRET"),
        ({"jwt_secret": "change-me-in-production"}, "JWT_SECRET"),
        ({"bootstrap_admin_password": "admin2024"}, "BOOTSTRAP_ADMIN_PASSWORD"),
        (
            {"database_url": "postgresql+psycopg://s:change-me-in-production@postgres:5432/s"},
            "DATABASE_URL",
        ),
    ],
)
def test_each_shipped_placeholder_is_detected(overrides, expected):
    problems = _unsafe_configuration(_settings(**overrides))
    assert any(expected in problem for problem in problems), problems


def test_a_short_secret_is_flagged_even_when_not_a_placeholder():
    problems = _unsafe_configuration(_settings(jwt_secret="tooshort"))
    assert any("shorter than 32" in problem for problem in problems)


def test_copying_env_example_into_production_is_caught():
    """The realistic failure mode: copy the template, flip the environment."""
    problems = _unsafe_configuration(
        _settings(
            jwt_secret="replace-with-a-long-random-string",
            bootstrap_admin_password="admin2024",
            database_url="postgresql+psycopg://scheduler:change-me-in-production@postgres:5432/scheduler",
        )
    )
    assert len(problems) == 3


# --------------------------------------------------------------------------- #
# Relative paths
# --------------------------------------------------------------------------- #


def test_relative_paths_anchor_to_the_project_root_not_the_cwd():
    """`cd backend && python -m app` must still write to <root>/storage.

    .env.example ships ./storage/deployments; resolving that against the
    working directory would hide uploads in backend/storage, where the
    documented backup never looks.
    """
    from app.config import PROJECT_ROOT

    settings = _settings(storage_dir="./storage/deployments", frontend_dist="./frontend/dist")
    assert settings.storage_dir == (PROJECT_ROOT / "storage" / "deployments").resolve()
    assert settings.frontend_dist == (PROJECT_ROOT / "frontend" / "dist").resolve()


def test_absolute_paths_are_left_alone():
    """Docker passes absolute paths; they must not be rewritten."""
    import pathlib

    absolute = pathlib.Path("/var/lib/pds/storage").resolve()
    settings = _settings(storage_dir=str(absolute))
    assert settings.storage_dir == absolute
