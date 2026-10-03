"""Load additive, repeatable AI demo records into the app's configured database.

PowerShell: Get-Content scripts/seed-ai-samples.py -Raw | docker compose exec -T app python -
"""
from datetime import date
import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models import BookingAssignment, Tenant, User
from app.seed import _add_change
from app.services import ai_access_service, assistant_service, group_service


SAMPLES = [
    ("NCAP", "2026-09-07", 1, "COMPLETED", "Databricks", "Deploy claims ingestion validation", "Claims ingestion validation completed successfully; schema checks passed."),
    ("EPCAT", "2026-09-07", 2, "FAILED", "AzDF", "Refresh the provider catalogue", "Provider catalogue refresh failed because the source service principal lacked storage permissions. No provider data was changed."),
    ("RADA", "2026-09-07", 3, "COMPLETED", "Application", "Release reporting dashboard", "Reporting dashboard release completed successfully with corrected regional filters."),
    ("NCAP", "2026-09-08", 1, "FAILED", "Databricks", "Update claims delta-table schema", "Claims schema deployment failed validation because a nullable partition key produced rejected records. Previous notebooks remained active."),
    ("EPCAT", "2026-09-08", 2, "COMPLETED", "AzDF", "Correct storage permissions and retry catalogue refresh", "Catalogue refresh completed after correcting the service principal storage permissions and rerunning validation."),
    ("RADA", "2026-09-08", 3, "ROLLED_BACK", "Database", "Add reporting indexes", "Reporting index deployment was rolled back after query latency increased during validation. The original index configuration was restored."),
    ("NCAP", "2026-10-11", 1, "BOOKED", "Databricks", "Fix nullable claims partition keys", "Planned fix normalizes nullable partition keys before ingestion, with schema validation and a rollback checkpoint."),
    ("EPCAT", "2026-10-11", 2, "BOOKED", "AzDF", "Add incremental catalogue refresh", "Planned incremental refresh reduces nightly workload and validates the provider catalogue row counts."),
    ("RADA", "2026-10-11", 3, "BOOKED", "Application", "Improve dashboard export", "Planned dashboard export change adds tenant and regional filters and checks output completeness."),
    ("NCAP", "2026-10-12", 1, "BOOKED", "Databricks", "Add ingestion quality monitoring", "Planned monitoring records invalid partition keys and alerts the on-call team when ingestion rejection thresholds are exceeded."),
    ("EPCAT", "2026-10-12", 2, "BOOKED", "Database", "Tune provider lookup indexes", "Planned provider lookup index tuning uses pre-deployment latency baselines and post-deployment checks."),
    ("RADA", "2026-10-12", None, "BOOKED", "Application", "Emergency reporting access hotfix", "Approved sample emergency hotfix restores reporting access after an authorization cache defect; verify access for each reporting role."),
]


with SessionLocal() as db:
    owner = db.scalar(select(User).where(User.is_owner.is_(True)))
    if owner is None:
        raise RuntimeError("The existing PDS Owner account is required; no demo login will be created.")
    tenants = {}
    for name in ("NCAP", "EPCAT", "RADA"):
        tenant = db.scalar(select(Tenant).where(Tenant.name == name))
        if tenant is None:
            tenant = Tenant(name=name, tenant_code=name, description=f"SAMPLE DATA: {name} AI demonstration tenant.")
            db.add(tenant)
            db.flush()
        group_service.ensure_tenant_group(db, tenant)
        tenants[name] = tenant

    created = []
    for index, (name, day, slot, state, tech, summary, description) in enumerate(SAMPLES, 1):
        emergency = slot is None
        emergency_fields = {
            "emergency_reason": "SAMPLE DATA: simulated production reporting access interruption.",
            "business_justification": "Restore reporting access for the demonstration scenario.",
            "emergency_approver": "Sample approval board",
            "emergency_approval_reference": "AI-DEMO-EMERGENCY-001",
        } if emergency else {}
        booking = _add_change(
            db, tenant=tenants[name], owner=owner, day=date.fromisoformat(day), slot=slot,
            is_emergency=emergency, jira_number=f"AI-DEMO-{index:03d}",
            change_number=f"CHGDEMO{index:04d}", environment="PROD", technology=tech,
            requester_name="AI Demo Requester", requester_email="ai-demo@example.com",
            verifier_name="AI Demo Verifier", verifier_email="ai-demo-verifier@example.com",
            git_repository="https://example.com/sample-repository",
            implementation_summary=f"SAMPLE DATA: {summary}.",
            deployment_description=f"SAMPLE DATA: {description}",
            justification="Synthetic deployment for testing assistant queries; no real deployment occurred.",
            impacted_region="APAC" if name != "RADA" else "EMEA",
            additional_comments="AI-DEMO sample record. Created for assistant testing.",
            status=state, **emergency_fields,
        )
        if booking is not None:
            if index not in {9, 11}:
                db.add(BookingAssignment(booking_id=booking.id, user_id=owner.id, assigned_by_user_id=owner.id))
            created.append({"schedule_no": booking.booking_reference.upper(), "tenant": name, "status": state})
    db.commit()
    print(json.dumps({"created": len(created), "records": created, "ai_master_enabled": ai_access_service.master_ai_enabled(db)}))
    print(json.dumps({"september": assistant_service.count_schedules(db, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)), "october": assistant_service.count_schedules(db, date_from=date(2026, 10, 1), date_to=date(2026, 10, 31))}))
