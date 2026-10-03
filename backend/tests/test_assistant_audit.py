"""Demo regressions: preserve filters and reject irrelevant evidence."""
from datetime import date

import pytest
from fastapi import HTTPException

from app.models import Tenant
from app.services import assistant_service, pds_api_agent, pds_chat_service, pds_rag_service
from test_assistant_api import _booking


@pytest.fixture
def audit_records(db, tenant):
    row = db.get(Tenant, tenant)
    for index, status in enumerate(["FAILED", "BOOKED", "COMPLETED", "BOOKED"], 1):
        item = _booking(tenant=row, reference=f"pds-{index:03d}", day=date(2026, 9, 7), slot=index, status=status, change=f"CHG{index:03d}")
        if index == 4:
            item.is_emergency = True
            item.slot_number = None
        db.add(item)
    db.commit()
    return row


@pytest.mark.parametrize("question, expected", [
    ("How many open deployments in September 2026?", "2"),
    ("How many closed deployments in September 2026?", "1"),
    ("Deployment summary of failed schedules in September 2026", "1"),
    ("How many emergency deployments in September 2026?", "1"),
    ("How many normal deployments in September 2026?", "3"),
])
def test_filtered_direct_answers(db, audit_records, monkeypatch, question, expected):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: pytest.fail("Direct query called AI"))
    answer = pds_chat_service.ask_pds_ai(db, message=question)
    assert answer["answer"].startswith(expected) or answer["answer"].startswith(f"There are {expected}")


def test_emergency_search_does_not_include_normal_rows(db, audit_records):
    output = pds_chat_service._ask_via_builtin(db, "Show emergency deployments in September 2026")
    assert "pds-004" in output["answer"]
    assert "pds-001" not in output["answer"]
    assert assistant_service.deployment_summary(db, is_emergency=True)["total"] == 1
    assert assistant_service.tenant_summary(db, tenant=audit_records.name, schedule_status="FAILED")["total"] == 1


def test_inactive_tenant_lookup_preserves_activity_filter(db, audit_records):
    audit_records.is_active = False
    db.commit()
    assert "1 inactive tenant" in pds_chat_service._ask_via_builtin(db, "Show inactive tenants")["answer"]
    assert "No active tenants" in pds_chat_service._ask_via_builtin(db, "Show active tenants")["answer"]


def test_unknown_tenant_cannot_be_replaced_by_global_counts(db, audit_records):
    assert pds_chat_service._answer_backend_question(db, "How many XYZ deployments are there?") is None
    result = pds_chat_service._run_question_tool(db, "count_schedules", {}, "How many XYZ deployments are there?")
    assert not result["ok"]
    assert "Preserve" in result["error"]


def test_user_question_cannot_be_verified_with_schedule_tool(db):
    result = pds_chat_service._run_question_tool(db, "count_schedules", {}, "Explain how many inactive management users there are")
    assert not result["ok"]


@pytest.mark.parametrize("arguments", ['[]', '{"active_only":"false"}', '{"is_emergency":"true"}'])
def test_malformed_tool_arguments_are_rejected(db, arguments):
    assert not pds_api_agent.handle_tool_call(db, "count_schedules", arguments)["ok"]


@pytest.mark.parametrize("question", ["Show my schedules", "What is the next slot for EPCAT?", "How many documents are uploaded?", "List management users"])
def test_unsupported_scopes_produce_honest_limitations(db, monkeypatch, question):
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: pytest.fail("Unsupported scope should be explained"))
    response = pds_chat_service.ask_pds_ai(db, message=question)
    assert "cannot" in response["answer"] or "not supported" in response["answer"]


def test_hosted_gateway_cannot_return_unverified_facts(db, monkeypatch):
    monkeypatch.setattr(pds_chat_service, "_post_response", lambda _payload: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "There are 999 deployments."}]}]})
    with pytest.raises(HTTPException, match="could not verify"):
        pds_chat_service._ask_via_responses(db, "Explain deployment history", [])


def test_filter_flags_are_consistent_in_rest_api(admin, audit_records):
    assert admin.put("/api/admin/ai-access", json={"ai_enabled": True}).status_code == 200
    response = admin.get("/api/assistant/count", params={"is_emergency": "true"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    response = admin.get("/api/assistant/deployment-summary", params={"status": "FAILED"})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_schedule_reference_shorthand_is_normalized():
    assert pds_chat_service._extract_schedule_no("Status of PDS-1?") == "pds-001"


def test_comparison_requires_both_requested_records(db, audit_records, monkeypatch):
    original_tool = pds_chat_service._run_tool
    def missing_second(session, name, arguments):
        if name == "get_schedule" and arguments.get("schedule_no") == "pds-002":
            return {"ok": False, "error": "Second record unavailable"}
        return original_tool(session, name, arguments)
    monkeypatch.setattr(pds_chat_service, "_run_tool", missing_second)
    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "get_schedule", "arguments": {"schedule_no": "pds-001"}}}]}},
        {"message": {"content": "The schedules have different outcomes."}},
        {"message": {"content": "The schedules have different outcomes."}},
    ])
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda *_args: "")
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: next(responses))
    with pytest.raises(HTTPException, match="could not verify"):
        pds_chat_service._ask_via_ollama_rag(db, "Compare PDS-001 and PDS-002", [])


def test_large_history_is_bounded_and_keeps_latest_question():
    history = [{"role": "user", "content": str(index) + "x" * 4000} for index in range(10)]
    clean = pds_chat_service._clean_history(history)
    assert sum(len(item["content"]) for item in clean) <= 6000
    assert clean[-1]["content"].startswith("9")


def test_count_followup_preserves_prior_explicit_filters(db, audit_records, monkeypatch):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: pytest.fail("Simple count follow-up must not infer a new scope"))
    response = pds_chat_service.ask_pds_ai(db, message="How many of those are there?", history=[
        {"role": "user", "content": "Show failed deployments in September 2026"},
        {"role": "assistant", "content": "RADA has other records; do not use this as the filter."},
    ])
    assert response["answer"].startswith("1 failed deployment")
    assert response["provider"] == "pds_backend_api"
