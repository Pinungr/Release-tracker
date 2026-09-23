"""Development sample data for the POC demo.

Run with:  python -m app.seed

Idempotent: rows that already exist are left alone. Creates the demo tenant
master, a demo TENANT_USER that owns the sample change records, one holiday,
and one emergency change so the admin-only queue is visible.

Never run this against production data.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from .database import SessionLocal
from .models import DeploymentBooking, Holiday, Tenant, User
from .security import hash_secret
from .services import audit_service, bootstrap
from .services.booking_service import next_booking_reference
from .utils.dates import today_local, week_start

DEMO_USERNAME = "demo.user"
DEMO_PASSWORD = "DemoPass!2026"

TENANTS = [
    ("Encounters", "ENCOUNTERS", "Claims encounter ingestion platform."),
    ("EPCAT", "EPCAT", "Provider catalogue and reference data."),
    ("Billing", "BILLING", "Billing and settlement services."),
]


def _ensure_tenants(db) -> dict[str, Tenant]:
    tenants: dict[str, Tenant] = {}
    for name, code, description in TENANTS:
        tenant = db.scalars(select(Tenant).where(Tenant.name == name)).first()
        if tenant is None:
            tenant = Tenant(name=name, tenant_code=code, description=description)
            db.add(tenant)
            db.flush()
        tenants[name] = tenant
    return tenants


def _ensure_demo_user(db) -> User:
    user = db.scalars(select(User).where(User.username == DEMO_USERNAME)).first()
    if user is None:
        user = User(
            full_name="Demo User",
            username=DEMO_USERNAME,
            email="demo.user@example.com",
            password_hash=hash_secret(DEMO_PASSWORD),
            role="TENANT_USER",
        )
        db.add(user)
        db.flush()
    return user


def _add_change(
    db,
    *,
    tenant: Tenant,
    owner: User,
    day: date,
    slot: int | None,
    is_emergency: bool = False,
    **fields,
) -> DeploymentBooking | None:
    """Creates one change record unless an equivalent one already exists."""
    existing = db.scalars(
        select(DeploymentBooking).where(
            DeploymentBooking.deployment_date == day,
            DeploymentBooking.jira_number == fields["jira_number"],
        )
    ).first()
    if existing is not None:
        return None

    booking = DeploymentBooking(
        booking_reference=next_booking_reference(db, day),
        deployment_date=day,
        slot_number=slot,
        is_emergency=is_emergency,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        created_by_user_id=owner.id,
        **{
            "justification": "Scheduled release approved by the tenant release board.",
            "impacted_region": "APAC",
            **fields,
        },
    )
    db.add(booking)
    db.flush()
    audit_service.record(
        db,
        event_type="EMERGENCY_BOOKING_CREATED" if is_emergency else "BOOKING_CREATED",
        booking=booking,
        actor_type="SYSTEM",
        requester_email=booking.requester_email,
        new_values=audit_service.snapshot(booking),
    )
    return booking


def run() -> None:
    bootstrap.initialise()
    monday = week_start(today_local()) + timedelta(days=7)
    tuesday = monday + timedelta(days=1)
    wednesday = monday + timedelta(days=2)

    with SessionLocal() as db:
        tenants = _ensure_tenants(db)
        owner = _ensure_demo_user(db)

        if db.scalars(select(Holiday).where(Holiday.holiday_date == monday)).first() is None:
            db.add(
                Holiday(
                    holiday_date=monday,
                    name="Indian Public Holiday",
                    description="No production deployments available.",
                    is_full_day=True,
                )
            )

        _add_change(
            db,
            tenant=tenants["Encounters"],
            owner=owner,
            day=tuesday,
            slot=1,
            jira_number="CHG0920798",
            jira_url="https://jira.example.com/browse/CHG0920798",
            environment="PROD",
            technology="Databricks",
            requester_name="Ananya Rao",
            requester_email="ananya.rao@example.com",
            requester_phone="+91 98450 11111",
            verifier_name="Siva Naga Raju",
            verifier_email="siva.raju@example.com",
            git_repository="https://github.example.com/encounters/etl-pipelines",
            implementation_summary="Deploy claim encounter ingestion notebooks and update the job cluster policy.",
            deployment_description="Release 4.2 of the encounters ingestion pipeline including schema evolution for the claims delta table.",
            additional_comments="Coordinate with the data platform on-call before starting.",
            status="BOOKED",
        )
        _add_change(
            db,
            tenant=tenants["EPCAT"],
            owner=owner,
            day=tuesday,
            slot=2,
            jira_number="CHG0920763",
            jira_url=None,
            environment="PROD",
            technology="AzDF",
            requester_name="Rahul Menon",
            requester_email="rahul.menon@example.com",
            requester_phone=None,
            verifier_name="Kalyani Sethuraman",
            verifier_email="kalyani.s@example.com",
            git_repository="https://github.example.com/epcat/data-factory",
            implementation_summary="Publish updated ADF pipelines for the provider catalogue refresh.",
            deployment_description="Adds the incremental provider catalogue refresh trigger and retires the legacy nightly copy activity.",
            status="BOOKED",
        )
        # Same person, a different tenant: users are never tied to one tenant.
        _add_change(
            db,
            tenant=tenants["Billing"],
            owner=owner,
            day=wednesday,
            slot=3,
            jira_number="CHG0921004",
            jira_url=None,
            environment="PROD",
            technology="Database",
            requester_name="Rahul Menon",
            requester_email="rahul.menon@example.com",
            requester_phone=None,
            verifier_name="Kalyani Sethuraman",
            verifier_email="kalyani.s@example.com",
            git_repository="https://github.example.com/billing/db-migrations",
            implementation_summary="Apply index and partition changes to the settlement schema.",
            deployment_description="Adds two covering indexes and repartitions the settlement_history table.",
            status="BOOKED",
        )
        # An emergency change sharing a date with normal ones: it occupies no
        # slot and does not count against the tenant's weekly quota.
        _add_change(
            db,
            tenant=tenants["Encounters"],
            owner=owner,
            day=tuesday,
            slot=None,
            is_emergency=True,
            jira_number="CHG0930911",
            jira_url=None,
            environment="PROD",
            technology="Application",
            requester_name="Platform On-call",
            requester_email="oncall@example.com",
            requester_phone=None,
            verifier_name="Siva Naga Raju",
            verifier_email="siva.raju@example.com",
            git_repository="https://github.example.com/encounters/hotfix",
            implementation_summary="Hotfix the claims ingestion pipeline to restore processing.",
            deployment_description="Roll forward notebook revision 4.2.1 which fixes the null partition key defect.",
            emergency_reason="Production outage in the claims ingestion pipeline.",
            business_justification="Claims processing is halted for all tenants until this is deployed.",
            emergency_approver="Head of Platform",
            emergency_approval_reference="EMG-2026-114",
            status="BOOKED",
        )
        db.commit()

    print(f"Sample data ready. Demo sign-in: {DEMO_USERNAME} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
