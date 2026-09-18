"""Development sample data.

Run with:  python -m app.seed

Idempotent: existing bookings/holidays with the same key are left alone.
Every sample booking uses the PIN 123456 so the edit/cancel flows can be
exercised immediately. Never run this against production data.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from .database import SessionLocal
from .models import DeploymentBooking, Holiday, Tenant
from .security import generate_manage_token, hash_manage_token, hash_secret
from .services import audit_service, bootstrap
from .services.booking_service import next_booking_reference, tenant_key
from .utils.dates import today_local, week_start

SAMPLE_PIN = "123456"


def _booking(db, *, reference_date: date, slot: int, **fields) -> DeploymentBooking | None:
    exists = db.scalars(
        select(DeploymentBooking).where(
            DeploymentBooking.deployment_date == reference_date,
            DeploymentBooking.slot_number == slot,
        )
    ).first()
    if exists is not None:
        return None
    tenant_name = fields["tenant_name"]
    tenant = db.scalars(select(Tenant).where(Tenant.name == tenant_name)).first()
    if tenant is None:
        tenant = Tenant(name=tenant_name, tenant_code=f"SEED-{tenant_key(tenant_name).upper()[:50]}")
        db.add(tenant)
        db.flush()
    booking = DeploymentBooking(
        booking_reference=next_booking_reference(db, reference_date),
        deployment_date=reference_date,
        slot_number=slot,
        tenant_id=tenant.id,
        tenant_key=tenant_key(fields["tenant_name"]),
        booking_pin_hash=hash_secret(SAMPLE_PIN),
        manage_token_hash=hash_manage_token(generate_manage_token()),
        **fields,
    )
    db.add(booking)
    db.flush()
    audit_service.record(
        db,
        event_type="BOOKING_CREATED",
        booking=booking,
        actor_type="SYSTEM",
        requester_email=booking.requester_email,
        new_values=audit_service.snapshot(booking),
    )
    return booking


def run() -> None:
    bootstrap.initialise()
    monday = week_start(date(2026, 9, 14))
    next_monday = week_start(today_local()) + timedelta(days=7)

    with SessionLocal() as db:
        if db.scalars(select(Holiday).where(Holiday.holiday_date == monday)).first() is None:
            db.add(
                Holiday(
                    holiday_date=monday,
                    name="Indian Public Holiday",
                    description="No production deployments available.",
                    is_full_day=True,
                    allow_emergency=True,
                )
            )

        _booking(
            db,
            reference_date=monday + timedelta(days=1),
            slot=1,
            tenant_name="Encounters",
            jira_change="CHG0920798",
            jira_task="CTASK3388771",
            jira_url="https://jira.example.com/browse/CHG0920798",
            environment="PROD",
            technology="Databricks",
            requester_name="Ananya Rao",
            requester_email="ananya.rao@example.com",
            requester_phone="+91 98450 11111",
            verifier_name="Siva Naga Raju",
            verifier_email="siva.raju@example.com",
            git_repository="https://github.example.com/encounters/etl-pipelines",
            implementation_summary="Deploy claim encounter ingestion notebooks and update job cluster policy.",
            deployment_description="Release 4.2 of the encounters ingestion pipeline including schema evolution for the claims delta table.",
            additional_comments="Coordinate with the data platform on-call before starting.",
            status="BOOKED",
        )
        _booking(
            db,
            reference_date=monday + timedelta(days=1),
            slot=2,
            tenant_name="EPCAT",
            jira_change="CHG0920763",
            jira_task=None,
            jira_url=None,
            environment="PROD",
            technology="AzDF",
            requester_name="Rahul Menon",
            requester_email="rahul.menon@example.com",
            requester_phone=None,
            verifier_name="Kalyani Sethuraman",
            verifier_email="kalyani.s@example.com",
            git_repository="https://github.example.com/epcat/data-factory",
            implementation_summary="Publish updated ADF pipelines for provider catalogue refresh.",
            deployment_description="Adds the incremental provider catalogue refresh trigger and retires the legacy nightly copy activity.",
            status="BOOKED",
        )
        _booking(
            db,
            reference_date=next_monday,
            slot=3,
            tenant_name="EPCAT",
            jira_change="CHG0921004",
            jira_task="CTASK3390115",
            jira_url=None,
            environment="PROD",
            technology="Database",
            requester_name="Rahul Menon",
            requester_email="rahul.menon@example.com",
            requester_phone=None,
            verifier_name="Kalyani Sethuraman",
            verifier_email="kalyani.s@example.com",
            git_repository="https://github.example.com/epcat/db-migrations",
            implementation_summary="Apply index and partition changes to the provider catalogue schema.",
            deployment_description="Adds two covering indexes and repartitions the provider_history table.",
            status="BOOKED",
        )
        db.commit()
    print("Sample data ready. Sample booking PIN:", SAMPLE_PIN)


if __name__ == "__main__":
    run()
