"""Test fixtures.

The environment is configured *before* the app package is imported so the
settings singleton points at a throwaway database and storage directory.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date, time, timedelta

import pytest

_TMP = tempfile.mkdtemp(prefix="pds-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["ADMIN_USERNAME"] = "testadmin"
os.environ["ADMIN_PASSWORD"] = "Sup3r-Secret-Pass"
os.environ["JWT_SECRET"] = "test-secret-key-long-enough-for-hs256-abcdef"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ApplicationSetting, BookingAudit, DeploymentBooking, Holiday  # noqa: E402
from app.security import ratelimit  # noqa: E402
from app.services import bootstrap  # noqa: E402
from app.utils.dates import today_local, week_start  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - cleanup
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    bootstrap.initialise()
    ratelimit.reset()
    yield
    with SessionLocal() as db:
        for model in (BookingAudit, DeploymentBooking, Holiday, ApplicationSetting):
            db.query(model).delete()
        db.commit()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/admin/login", json={"username": "testadmin", "password": "Sup3r-Secret-Pass"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def next_monday() -> date:
    """A Monday far enough ahead to sit outside the 48-hour freeze window."""
    return week_start(today_local()) + timedelta(days=14)


def booking_payload(day: date, slot: int, **overrides) -> dict:
    payload = {
        "tenant_name": "EPCAT",
        "jira_change": "CHG0920763",
        "jira_task": "CTASK3388771",
        "jira_url": "https://jira.example.com/browse/CHG0920763",
        "environment": "PROD",
        "technology": "Databricks",
        "requester_name": "Rahul Menon",
        "requester_email": "rahul.menon@example.com",
        "requester_phone": "+91 98450 22222",
        "verifier_name": "Kalyani Sethuraman",
        "verifier_email": "kalyani.s@example.com",
        "git_repository": "https://github.example.com/epcat/data-factory",
        "implementation_summary": "Publish updated pipelines for the provider catalogue refresh.",
        "deployment_description": "Adds the incremental refresh trigger and retires the nightly copy.",
        "additional_comments": None,
        "deployment_date": day.isoformat(),
        "slot_number": slot,
        "booking_pin": "123456",
        "confirm_booking_pin": "123456",
    }
    payload.update(overrides)
    return payload


def emergency_payload(day: date, slot: int = 5, **overrides) -> dict:
    payload = booking_payload(day, slot)
    payload.update(
        {
            "emergency_reason": "Production outage in the claims ingestion pipeline.",
            "business_justification": "Claims processing is halted for all tenants.",
            "emergency_approver": "Head of Platform",
            "emergency_approval_reference": "EMG-2026-114",
        }
    )
    payload.update(overrides)
    return payload


SLOT_START_TIMES = {1: time(7, 0), 2: time(9, 0), 3: time(11, 0), 4: time(14, 0), 5: time(16, 0)}
