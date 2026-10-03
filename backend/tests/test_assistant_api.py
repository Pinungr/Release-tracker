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

    response = user.post("/api/assistant/chat", json={"message": "Explain the operational significance of deployment history.", "history": []})
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

    response = user.post("/api/assistant/chat", json={"message": "Explain the operational significance of deployment history.", "history": []})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "There are 0 PDS schedules."
    assert response.json()["read_only"] is True
    assert len(calls) == 2
    assert "previous_response_id" not in calls[1]
    tool_output_item = next(item for item in calls[1]["input"] if item.get("type") == "function_call_output")
    tool_output = json.loads(tool_output_item["output"])
    assert tool_output["ok"] is True
    assert tool_output["result"]["total"] == 0


def test_pds_api_agent_uses_authoritative_assistant_service(db, monkeypatch):
    from app.services import assistant_service, pds_api_agent

    received: dict = {}

    def fake_count_schedules(session, **filters):
        received["session"] = session
        received.update(filters)
        return {"total": 3, "by_status": {"FAILED": 3}}

    monkeypatch.setattr(assistant_service, "count_schedules", fake_count_schedules)
    result = pds_api_agent.handle_tool_call(
        db,
        "count_schedules",
        '{"tenant":"NCAP","date_from":"2026-09-01","date_to":"2026-09-30","status":"FAILED"}',
    )

    assert result == {"ok": True, "result": {"total": 3, "by_status": {"FAILED": 3}}}
    assert received == {
        "session": db,
        "tenant": "NCAP",
        "date_from": date(2026, 9, 1),
        "date_to": date(2026, 9, 30),
        "schedule_status": "FAILED",
    }


def test_next_available_slot_uses_board_bookable_state(db, monkeypatch):
    from types import SimpleNamespace

    from app.services import availability_service

    today = date(2026, 10, 3)
    monday = date(2026, 10, 4)
    available_day = date(2026, 10, 5)
    monkeypatch.setattr(availability_service, "today_local", lambda: today)
    monkeypatch.setattr(availability_service, "week_start", lambda day: date(2026, 10, 4))
    monkeypatch.setattr(
        availability_service.presenters,
        "schedule_response",
        lambda *_args, **_kwargs: SimpleNamespace(
            week_start=monday,
            days=[
                SimpleNamespace(
                    day=today,
                    weekday="Saturday",
                    slots=[SimpleNamespace(bookable=True)],
                ),
                SimpleNamespace(
                    day=monday,
                    weekday="Sunday",
                    slots=[SimpleNamespace(bookable=False)],
                ),
                SimpleNamespace(
                    day=available_day,
                    weekday="Monday",
                    slots=[
                        SimpleNamespace(
                            bookable=True,
                            slot_number=2,
                            name="Morning",
                            time_label="09:00 - 10:00",
                        )
                    ],
                ),
            ],
        ),
    )

    result = availability_service.next_available_slot(db)

    assert result["available"] is True
    assert result["deployment_date"] == available_day.isoformat()
    assert result["slot_number"] == 2
    assert result["slot_name"] == "Morning"


def test_next_slot_question_uses_authoritative_api_without_qwen(user, admin, monkeypatch):
    from app.services import availability_service, pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_chat_service.settings, "ai_base_url", "http://localhost:11434")
    monkeypatch.setattr(pds_chat_service.settings, "ai_model", "qwen3:8b")
    monkeypatch.setattr(pds_chat_service.settings, "ai_embedding_model", "nomic-embed-text")
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda _db, _query: "")
    next_slot = {
        "available": True,
        "deployment_date": "2026-10-05",
        "weekday": "Monday",
        "slot_number": 2,
        "slot_name": "Morning",
        "time_label": "09:00 - 10:00",
        "week_start": "2026-10-04",
        "search_through": "2026-12-02",
        "search_days": 60,
    }
    monkeypatch.setattr(
        availability_service, "next_available_slot", lambda _db: next_slot
    )
    def fake_chat(**_kwargs):
        raise AssertionError("Direct slot lookup must not call the model")

    monkeypatch.setattr(pds_rag_service, "chat", fake_chat)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "when is the next slot available ?", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == (
        "The next available deployment slot is Monday, October 5, 2026: Morning (Slot 2), 09:00 - 10:00."
    )
    assert response.json()["provider"] == "pds_backend_api"
    assert response.json()["model"] == "PDS scheduling API"


def test_next_slot_unavailable_answer_is_limited_to_search_horizon():
    from app.services.pds_chat_service import _format_next_slot_result

    answer = _format_next_slot_result(
        {
            "available": False,
            "search_days": 60,
            "search_through": "2026-12-02",
        }
    )

    assert answer == (
        "I couldn't find a bookable deployment slot in the next 60 days, "
        "through December 2, 2026. That search doesn't rule out availability after this period."
    )


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


def test_structured_backend_question_works_without_ollama(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def ollama_unavailable(*_args, **_kwargs):
        from fastapi import HTTPException

        raise HTTPException(502, "Ollama is unavailable.")

    monkeypatch.setattr(pds_rag_service, "retrieve_context", ollama_unavailable)
    monkeypatch.setattr(pds_rag_service, "chat", ollama_unavailable)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "How many schedules are there?", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == (
        "There are 0 schedules."
    )
    assert response.json()["provider"] == "pds_backend_api"
    assert response.json()["model"] == "PDS backend API"
    assert response.json()["read_only"] is True


def test_tenant_question_works_without_ollama(user, admin, tenant, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def ollama_unavailable(*_args, **_kwargs):
        from fastapi import HTTPException

        raise HTTPException(502, "Ollama is unavailable.")

    monkeypatch.setattr(pds_rag_service, "retrieve_context", ollama_unavailable)
    monkeypatch.setattr(pds_rag_service, "chat", ollama_unavailable)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "How many tenants are configured?", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == (
        "1 tenant is configured: EPCAT."
    )
    assert response.json()["provider"] == "pds_backend_api"
    assert response.json()["read_only"] is True


def test_structured_api_facts_never_call_qwen(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("Direct facts must not call embeddings or chat")

    monkeypatch.setattr(pds_rag_service, "retrieve_context", unexpected_model)
    monkeypatch.setattr(pds_rag_service, "chat", unexpected_model)
    response = user.post("/api/assistant/chat", json={"message": "How many schedules are there?"})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "There are 0 schedules."
    assert response.json()["provider"] == "pds_backend_api"


def test_qwen_reasoning_is_not_replaced_with_api_fallback(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(
        pds_rag_service,
        "chat",
        lambda **_kwargs: {
            "message": {
                "role": "assistant",
                "content": "Let me think. The user asked about the schedule count.",
            }
        },
    )
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda *_args: "")
    response = user.post(
        "/api/assistant/chat",
        json={"message": "Explain the operational significance of deployment history.", "history": []},
    )

    assert response.status_code == 502
    assert "concise user-facing answer" in response.json()["detail"]


def test_local_qwen_rag_uses_retrieved_context_and_read_only_database_tools(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_chat_service.settings, "ai_base_url", "http://localhost:11434")
    monkeypatch.setattr(pds_chat_service.settings, "ai_model", "qwen3:8b")
    monkeypatch.setattr(pds_chat_service.settings, "ai_embedding_model", "nomic-embed-text")
    monkeypatch.setattr(
        pds_rag_service,
        "retrieve_context",
        lambda _db, _query: "Schedule PDS-901\nTenant: NCAP\nStatus: FAILED",
    )

    sent_messages: list[list[dict]] = []
    responses = iter(
        [
            {
                "model": "qwen3:8b",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "count_schedules",
                                "arguments": {
                                    "tenant": None,
                                    "date_from": None,
                                    "date_to": None,
                                    "status": "FAILED",
                                },
                            }
                        }
                    ],
                },
            },
            {
                "model": "qwen3:8b",
                "message": {
                    "role": "assistant",
                    "content": "There are no failed PDS schedules in the database.",
                },
            },
        ]
    )

    def fake_chat(*, messages, tools):
        sent_messages.append(messages)
        assert tools[0]["function"]["name"] == "get_schedule"
        return next(responses)

    monkeypatch.setattr(pds_rag_service, "chat", fake_chat)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "Explain the operational significance of deployment history.", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "There are no failed PDS schedules in the database."
    assert response.json()["provider"] == "ollama_rag"
    assert response.json()["model"] == "qwen3:8b"
    assert response.json()["read_only"] is True
    assert "Schedule PDS-901" in sent_messages[0][0]["content"]
    tool_result = next(message for message in sent_messages[1] if message["role"] == "tool")
    assert '"total": 0' in tool_result["content"]


def test_local_qwen_rag_refuses_unverified_factual_answer(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_chat_service.settings, "ai_base_url", "http://localhost:11434")
    monkeypatch.setattr(pds_chat_service.settings, "ai_model", "qwen3:8b")
    monkeypatch.setattr(pds_chat_service.settings, "ai_embedding_model", "nomic-embed-text")
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda _db, _query: "")
    responses = iter(
        [
            {"message": {"role": "assistant", "content": "There are 12 schedules."}},
            {"message": {"role": "assistant", "content": "There are 12 schedules."}},
        ]
    )
    calls: list[list[dict]] = []

    def fake_chat(*, messages, tools):
        calls.append(messages)
        return next(responses)

    monkeypatch.setattr(pds_rag_service, "chat", fake_chat)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "Explain the operational significance of deployment history.", "history": []},
    )

    assert response.status_code == 502
    assert "could not verify" in response.json()["detail"]
    assert len(calls) == 2
    assert "Call the appropriate" in calls[1][-1]["content"]


def test_failed_backend_api_tool_does_not_verify_model_answer(user, admin, monkeypatch):
    from app.services import pds_chat_service, pds_rag_service

    _enable_ai_override(admin, user)
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_chat_service.settings, "ai_base_url", "http://localhost:11434")
    monkeypatch.setattr(pds_chat_service.settings, "ai_model", "qwen3:8b")
    monkeypatch.setattr(pds_chat_service.settings, "ai_embedding_model", "nomic-embed-text")
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda _db, _query: "")
    responses = iter(
        [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "count_schedules",
                                "arguments": {
                                    "tenant": None,
                                    "date_from": None,
                                    "date_to": None,
                                    "status": "NOT_A_STATUS",
                                },
                            }
                        }
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "There are 12 schedules."}},
            {"message": {"role": "assistant", "content": "There are 12 schedules."}},
        ]
    )
    calls: list[list[dict]] = []

    def fake_chat(*, messages, tools):
        calls.append(messages)
        return next(responses)

    monkeypatch.setattr(pds_rag_service, "chat", fake_chat)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "Explain the operational significance of deployment history.", "history": []},
    )

    assert response.status_code == 502
    assert "could not verify" in response.json()["detail"]
    tool_result = next(message for message in calls[1] if message["role"] == "tool")
    assert '"ok": false' in tool_result["content"]
    assert len(calls) == 3


def test_schedule_lookup_uses_authoritative_backend_without_qwen(user, admin, db, tenant, monkeypatch):
    from app.services import pds_rag_service

    _enable_ai_override(admin, user)
    tenant_row = db.get(Tenant, tenant)
    rm = db.scalar(select(User).where(User.username == "testadmin"))
    assert tenant_row is not None
    assert rm is not None
    booking = _booking(
        tenant=tenant_row,
        reference="pds-001",
        day=date(2026, 10, 5),
        slot=1,
        status=BookingStatus.BOOKED.value,
        change="CHG00001",
    )
    db.add(booking)
    db.flush()
    db.add(BookingAssignment(booking_id=booking.id, user_id=rm.id, assigned_by_user_id=rm.id))
    db.commit()

    def fake_model_call(**_kwargs):
        raise AssertionError("Direct schedule lookups must not call Qwen")

    def unexpected_retrieval(*_args, **_kwargs):
        raise AssertionError("Schedule lookups use the backend API.")

    monkeypatch.setattr(pds_rag_service, "retrieve_context", unexpected_retrieval)
    monkeypatch.setattr(pds_rag_service, "chat", fake_model_call)
    response = user.post(
        "/api/assistant/chat",
        json={"message": "Who is the Release Manager for PDS-001?", "history": []},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == f"The Release Manager for PDS-001 is {rm.full_name}."
    assert response.json()["provider"] == "pds_backend_api"
    assert response.json()["model"] == "PDS backend API"
    assert response.json()["read_only"] is True


def test_model_internal_reasoning_is_rejected():
    import pytest
    from fastapi import HTTPException

    from app.services.pds_chat_service import _require_user_facing_answer

    with pytest.raises(HTTPException) as error:
        _require_user_facing_answer(
            "Okay, let me think. The user asked who is assigned, so I should check."
        )

    assert error.value.status_code == 502
    assert "concise user-facing answer" in error.value.detail


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
