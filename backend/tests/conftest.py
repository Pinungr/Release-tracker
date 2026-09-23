"""Test fixtures.

The environment is configured *before* the app package is imported so the
settings singleton points at a throwaway database and storage directory.

SQLite is used here deliberately: it gives every test a fresh, isolated,
in-process schema in milliseconds. Production runs on PostgreSQL (see the
README); nothing in the application depends on which of the two is behind
SQLAlchemy.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date, timedelta

import pytest

_TMP = tempfile.mkdtemp(prefix="pds-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "testadmin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "Sup3r-Secret-Pass"
os.environ["JWT_SECRET"] = "test-secret-key-long-enough-for-hs256-abcdef"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import ratelimit  # noqa: E402
from app.services import bootstrap  # noqa: E402
from app.utils.dates import today_local, week_start  # noqa: E402

ADMIN_USERNAME = "testadmin"
ADMIN_PASSWORD = "Sup3r-Secret-Pass"


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - cleanup
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_database():
    """Every test starts from an empty migrated schema plus the bootstrap admin."""
    # Reset Alembic's version table along with the model tables so bootstrap
    # exercises the complete existing migration chain on every clean database.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    bootstrap.initialise()
    ratelimit.reset()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def anon() -> TestClient:
    """Unauthenticated client, for sign-up/login and authorization tests."""
    with TestClient(app) as client:
        yield client


def register(client: TestClient, username: str, password: str = "StrongPass!123") -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": f"{username.title()} Person",
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def login(client: TestClient, username: str, password: str = "StrongPass!123") -> str:
    response = client.post(
        "/api/auth/login", json={"username_or_email": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def authenticated(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def sign_up_and_login(anon: TestClient, username: str) -> TestClient:
    register(anon, username)
    return authenticated(login(anon, username))


@pytest.fixture
def admin(anon: TestClient) -> TestClient:
    """The bootstrap administrator, signed in through the one shared login."""
    client = authenticated(login(anon, ADMIN_USERNAME, ADMIN_PASSWORD))
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def user(anon: TestClient) -> TestClient:
    """A self-registered TENANT_USER."""
    client = sign_up_and_login(anon, "pinaki")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def other_user(anon: TestClient) -> TestClient:
    """A second TENANT_USER, for cross-user authorization tests."""
    client = sign_up_and_login(anon, "user2")
    try:
        yield client
    finally:
        client.close()


def promote_to_release_manager(owner: TestClient, user_client: TestClient) -> int:
    """Promote an existing tenant user to the non-owner ADMIN role shown as Release Manager."""
    user_id = user_client.get("/api/auth/me").json()["id"]
    response = owner.patch(f"/api/admin/users/{user_id}/role", json={"role": "ADMIN"})
    assert response.status_code == 200, response.text
    return user_id


def create_tenant(admin: TestClient, name: str, code: str | None = None) -> int:
    response = admin.post(
        "/api/admin/tenants",
        json={"name": name, "tenant_code": code or name.upper().replace(" ", "-")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def tenant(admin: TestClient) -> int:
    return create_tenant(admin, "EPCAT")


@pytest.fixture
def other_tenant(admin: TestClient) -> int:
    return create_tenant(admin, "Encounters")


@pytest.fixture
def next_monday() -> date:
    """A valid future deployment date used by scheduling tests."""
    return week_start(today_local()) + timedelta(days=14)


def booking_payload(tenant_id: int, day: date, slot: int, **overrides) -> dict:
    """A complete normal change record. Tenant comes from the master by id."""
    payload = {
        "tenant_id": tenant_id,
        "jira_number": "CHG0920763",
        "jira_url": "https://jira.example.com/browse/CHG0920763",
        "technology": "Databricks",
        "verifier_name": "Kalyani Sethuraman",
        "verifier_email": "kalyani.s@example.com",
        "git_repository": "https://github.example.com/epcat/data-factory",
        "implementation_summary": "Publish updated pipelines for the provider catalogue refresh.",
        "deployment_description": "Adds the incremental refresh trigger and retires the nightly copy.",
        "justification": "Contractual go-live date for the provider catalogue refresh.",
        "impacted_region": "APAC",
        "additional_comments": None,
        "deployment_date": day.isoformat(),
        "slot_number": slot,
    }
    payload.update(overrides)
    return payload


def emergency_payload(tenant_id: int, day: date, **overrides) -> dict:
    """An emergency change: no slot number, it joins the date's queue."""
    payload = booking_payload(tenant_id, day, slot=None)
    payload.update(
        {
            "slot_number": None,
            "is_emergency": True,
            "emergency_reason": "Production outage in the claims ingestion pipeline.",
            "business_justification": "Claims processing is halted for all tenants.",
            "emergency_approver": "Head of Platform",
            "emergency_approval_reference": "EMG-2026-114",
        }
    )
    payload.update(overrides)
    return payload


REQUIRED_BOOKING_DOCUMENTS = {
    "TEST_RESULTS": ("non-prod-results.pdf", b"non-prod test evidence"),
    "INVENTORY": ("inventory.xlsx", b"inventory evidence"),
    "IMPLEMENTATION_PLAN": ("implementation.docx", b"implementation plan"),
    "VALIDATION_PLAN": ("validation.docx", b"validation plan"),
    "DBA_SCRIPT": ("dba.sql", b"-- dba script"),
}


def post_booking(
    client: TestClient,
    payload: dict,
    *,
    omit_documents: set[str] | None = None,
):
    """Create through the production multipart booking contract."""
    omit = omit_documents or set()
    files = [
        (f"document_{category}", (filename, content, "application/octet-stream"))
        for category, (filename, content) in REQUIRED_BOOKING_DOCUMENTS.items()
        if category not in omit
    ]
    return client.post(
        "/api/bookings",
        data={"payload": json.dumps(payload)},
        files=files,
    )


def create_booking(client: TestClient, tenant_id: int, day: date, slot: int, **overrides) -> dict:
    response = post_booking(client, booking_payload(tenant_id, day, slot, **overrides))
    assert response.status_code == 201, response.text
    return response.json()["booking"]
