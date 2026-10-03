"""Read-only assistant API regression coverage."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import BookingAssignment, BookingStatus, DeploymentBooking, Tenant, User


def _booking(*, tenant: Tenant, reference: str, day: date, slot: int, status: str, change: str):
    return DeploymentBooking(
        booking_reference=reference,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        deployment_date=day,
        slot_number=slot,
        jira_number=None,
        jira_url=None,
        change_number=change,
        environment="PROD",
        technology="Databricks",
        requester_name="PDS Test User",
        requester_email="pds-test@example.com",
        verifier_name="Verifier",
        verifier_email="verifier@example.com",
        git_repository="https://git.example.com/pds/test",
        implementation_summary="Test deployment",
        deployment_description="Assistant API test record",
        additional_comments=None,
        justification="Regression test",
        impacted_region="APAC",
        status=status,
        is_emergency=False,
    )




def _enable_ai_override(admin, user):
    user_id = user.get("/api/auth/me").json()["id"]
    groups = admin.get("/api/admin/groups").json()
    ai_group = next(group for group in groups if group["group_type"] == "AI_USERS")
    added = admin.post(f"/api/admin/groups/{ai_group['id']}/members/{user_id}")
    assert added.status_code == 200, added.text
    updated = admin.put("/api/admin/ai-access", json={"ai_enabled": True})
    assert updated.status_code == 200, updated.text

def test_assistant_requires_authentication(anon):
    response = anon.get("/api/assistant/count")
    assert response.status_code == 401


def test_assistant_count_summary_schedule_and_rm(user, admin, db, tenant):
    _enable_ai_override(admin, user)
    tenant_row = db.get(Tenant, tenant)
    rm = db.scalar(select(User).where(User.username == "testadmin"))
    assert tenant_row is not None
    assert rm is not None

    first = _booking(
        tenant=tenant_row,
        reference="pds-901",
        day=date(2026, 9, 10),
        slot=1,
        status=BookingStatus.COMPLETED.value,
        change="CHG00901",
    )
    second = _booking(
        tenant=tenant_row,
        reference="pds-902",
        day=date(2026, 9, 11),
        slot=2,
        status=BookingStatus.FAILED.value,
        change="CHG00902",
    )
    db.add_all([first, second])
    db.flush()
    db.add(BookingAssignment(booking_id=first.id, user_id=rm.id, assigned_by_user_id=rm.id))
    db.commit()

    count = user.get(
        "/api/assistant/count",
        params={"tenant": tenant_row.name, "date_from": "2026-09-01", "date_to": "2026-09-30"},
    )
    assert count.status_code == 200, count.text
    body = count.json()
    assert body["total"] == 2
    assert body["by_status"] == {"COMPLETED": 1, "FAILED": 1}

    detail = user.get("/api/assistant/schedules/pds-901")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["change_number"] == "CHG00901"
    assert payload["release_managers"][0]["full_name"] == rm.full_name

    summary = user.get(
        f"/api/assistant/tenant-summary/{tenant_row.name}",
        params={"date_from": "2026-09-01", "date_to": "2026-09-30"},
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["release_manager_assignments"] == {rm.full_name: 1}


def test_assistant_rejects_bad_date_range(user, admin):
    _enable_ai_override(admin, user)
    response = user.get(
        "/api/assistant/count",
        params={"date_from": "2026-10-01", "date_to": "2026-09-01"},
    )
    assert response.status_code == 422


def test_assistant_rejects_unknown_status(user, admin):
    _enable_ai_override(admin, user)
    response = user.get("/api/assistant/count", params={"status": "NOT_A_REAL_STATUS"})
    assert response.status_code == 422


def test_external_gateway_reports_when_ai_key_is_missing(user, admin, monkeypatch):
    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "org_gateway")
    monkeypatch.setattr(pds_chat_service.settings, "ai_api_key", "")

    response = user.post("/api/assistant/chat", json={"message": "How many schedules are there?", "history": []})
    assert response.status_code == 503
    assert "AI_API_KEY" in response.json()["detail"]


def test_chat_uses_only_the_read_only_tool_loop(user, admin, monkeypatch):
    import json

    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "org_gateway")
    monkeypatch.setattr(pds_chat_service.settings, "ai_api_key", "test-key")
    calls: list[dict] = []
    responses = iter(
        [
            {
                "id": "resp-1",
                "model": "test-model",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "count_schedules",
                        "arguments": json.dumps(
                            {"tenant": None, "date_from": None, "date_to": None, "status": None}
                        ),
                    }
                ],
            },
            {
                "id": "resp-2",
                "model": "test-model",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "There are 0 PDS schedules."}],
                    }
                ],
            },
        ]
    )

    def fake_post(payload):
        calls.append(payload)
        return next(responses)

    monkeypatch.setattr(pds_chat_service, "_post_response", fake_post)

    response = user.post("/api/assistant/chat", json={"message": "How many schedules are there?", "history": []})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "There are 0 PDS schedules."
    assert response.json()["read_only"] is True
    assert len(calls) == 2
    assert "previous_response_id" not in calls[1]
    tool_output_item = next(item for item in calls[1]["input"] if item.get("type") == "function_call_output")
    tool_output = json.loads(tool_output_item["output"])
    assert tool_output["ok"] is True
    assert tool_output["result"]["total"] == 0


def test_builtin_chat_works_without_ai_api_key(user, admin, monkeypatch):
    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "builtin")
    monkeypatch.setattr(pds_chat_service.settings, "ai_api_key", "")

    response = user.post("/api/assistant/chat", json={"message": "How many schedules are there?", "history": []})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "There are 0 schedules."
    assert response.json()["provider"] == "builtin"
    assert response.json()["model"] == "Rule-based"
    assert response.json()["read_only"] is True


def test_builtin_chat_handles_tenant_month_count(user, admin, db, tenant, monkeypatch):
    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "builtin")
    tenant_row = db.get(Tenant, tenant)
    assert tenant_row is not None
    db.add(
        _booking(
            tenant=tenant_row,
            reference="pds-955",
            day=date(2026, 9, 15),
            slot=1,
            status=BookingStatus.COMPLETED.value,
            change="CHG00955",
        )
    )
    db.commit()

    response = user.post(
        "/api/assistant/chat",
        json={"message": f"How many {tenant_row.name} releases happened in September 2026?", "history": []},
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == f"1 {tenant_row.name} release occurred in September 2026."


def test_builtin_chat_stays_read_only(user, admin, monkeypatch):
    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "builtin")
    response = user.post("/api/assistant/chat", json={"message": "Cancel PDS-001", "history": []})
    assert response.status_code == 200, response.text
    assert "read-only" in response.json()["answer"]


def test_tenant_list_tool_returns_configured_tenants(user, admin, tenant):
    _enable_ai_override(admin, user)
    response = user.get("/api/assistant/tenants")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    assert any(item["id"] == tenant for item in payload["tenants"])


def test_access_reports_builtin_provider(user, admin, monkeypatch):
    from app.services import pds_chat_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "builtin")
    monkeypatch.setattr(pds_chat_service.settings, "ai_api_key", "")

    response = user.get("/api/assistant/access")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["chat_configured"] is True
    assert payload["provider"] == "builtin"
    assert payload["provider_label"] == "Built-in PDS"
    assert payload["model"] == "Rule-based"


def test_direct_schedule_formatter_answers_release_manager_only():
    from app.services import pds_chat_service

    output = {
        "ok": True,
        "result": {
            "schedule_no": "pds-001",
            "status": "BOOKED",
            "tenant": "NCAP",
            "deployment_date": "2026-10-04",
            "change_number": None,
            "release_managers": [{"full_name": "Release Manager One"}],
        },
    }
    answer = pds_chat_service._format_direct_tool_answer(
        "get_schedule", output, "Who is the Release Manager for PDS-001?"
    )
    assert answer == "The Release Manager for PDS-001 is Release Manager One."


def test_direct_schedule_formatter_handles_unassigned_release_manager():
    from app.services import pds_chat_service

    output = {
        "ok": True,
        "result": {
            "schedule_no": "pds-001",
            "status": "BOOKED",
            "tenant": "NCAP",
            "deployment_date": "2026-10-04",
            "change_number": None,
            "release_managers": [],
        },
    }
    answer = pds_chat_service._format_direct_tool_answer(
        "get_schedule", output, "Who is the RM for PDS-001?"
    )
    assert answer == "No Release Manager is currently assigned to PDS-001."
