"""Hybrid routing contracts: direct data bypasses AI; reasoning retains agents."""
import pytest

from app.services import pds_api_agent, pds_chat_service, pds_rag_service, pds_query_plan


@pytest.mark.parametrize("question", [
    "How many schedules are there?", "List tenants", "Show deployments this month",
    "Who is the RM for PDS-001?", "What is the Change No. for PDS-001?",
    "What is the status of PDS-001?", "Deployment summary this month",
    "How many deployments for tenant EPCAT this month?", "hello",
])
def test_direct_questions_do_not_use_models(db, tenant, monkeypatch, question):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def unexpected(*_args, **_kwargs):
        pytest.fail("Direct questions must not call a model or FAISS")

    monkeypatch.setattr(pds_rag_service, "chat", unexpected)
    monkeypatch.setattr(pds_rag_service, "retrieve_context", unexpected)
    original = pds_chat_service._run_tool

    def tool(session, name, arguments):
        if name == "get_schedule":
            return {"ok": True, "result": {"schedule_no": "pds-001", "status": "BOOKED"}}
        return original(session, name, arguments)

    monkeypatch.setattr(pds_chat_service, "_run_tool", tool)
    result = pds_chat_service.ask_pds_ai(db, message=question)
    assert result["provider"] in {"builtin", "pds_backend_api"}
    assert result["read_only"] is True


@pytest.mark.parametrize("question", [
    "Explain the purpose of PDS-001", "Compare PDS-001 and PDS-002",
    "Why did EPCAT deployments fail?", "Summarize implementation for PDS-001",
    "How many schedules last week?", "How many deployments on September 10?",
    "Show failed or completed deployments", "How many releases excluding emergency changes?",
    "Summarize PDS-001 in plain language",
])
def test_reasoning_and_unsupported_filters_reach_intelligence(db, monkeypatch, question):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    captured = {}

    def reasoning(session, message, history):
        captured["message"] = message
        return {"answer": "Verified reasoning", "provider": "ollama_rag", "read_only": True}

    monkeypatch.setattr(pds_chat_service, "_ask_via_ollama_rag", reasoning)
    monkeypatch.setattr(pds_query_plan, "answer", reasoning)
    assert pds_chat_service.ask_pds_ai(db, message=question)["provider"] == "ollama_rag"
    assert captured["message"] == question


def test_contextual_followup_keeps_history(db, monkeypatch):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    history = [{"role": "user", "content": "Show failed deployments in September"}]

    def reasoning(session, message, previous):
        assert previous == history
        return {"answer": "Context preserved", "provider": "ollama_rag"}

    monkeypatch.setattr(pds_chat_service, "_ask_via_ollama_rag", reasoning)
    response = pds_chat_service.ask_pds_ai(db, message="Explain why those failed", history=history)
    assert response["provider"] == "ollama_rag"


def test_app_guidance_uses_app_agent_without_database_embeddings(db, monkeypatch):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def unexpected(*_args, **_kwargs):
        pytest.fail("Generic app guidance does not need database retrieval")

    def chat(*, messages, tools):
        assert "PDS application guide" in messages[0]["content"]
        assert "read-only" in messages[0]["content"]
        return {"message": {"content": "Choose a tenant and reserve a slot on the weekly board."}}

    monkeypatch.setattr(pds_rag_service, "retrieve_context", unexpected)
    monkeypatch.setattr(pds_rag_service, "chat", chat)
    answer = pds_chat_service.ask_pds_ai(db, message="How do I schedule a deployment?")
    assert answer["provider"] == "ollama_rag"


def test_invalid_direct_date_is_validation_error(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        pds_chat_service.ask_pds_ai(db, message="How many schedules on 2026-99-99?")
    assert exc.value.status_code == 422


def test_real_faiss_index_retrieves_vectors_without_chat(monkeypatch):
    numpy, faiss = pds_rag_service._libraries()
    vectors = {"Release A": [1, 0], "Release B": [0, 1], "query": [1, 0]}
    monkeypatch.setattr(pds_rag_service, "_embed_texts", lambda texts: [vectors[t] for t in texts])
    index = pds_rag_service._build_index(["Release A", "Release B"], numpy, faiss)
    scores, matches = index.search(numpy.asarray([vectors["query"]], dtype=numpy.float32), 1)
    assert int(matches[0][0]) == 0
    assert float(scores[0][0]) == pytest.approx(1.0)


def test_unknown_database_tool_is_rejected(db):
    output = pds_api_agent.handle_tool_call(db, "delete_schedule", {"schedule_no": "PDS-001"})
    assert output["ok"] is False


def test_unknown_explicit_tenant_does_not_return_global_counts(db, monkeypatch):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    assert pds_chat_service._extract_tenant(db, "How many deployments for tenant UNKNOWN?") == "unknown"
    monkeypatch.setattr(pds_chat_service, "_ask_via_ollama_rag", lambda *_args: {"answer": "Retry with verified tenants", "provider": "ollama_rag"})
    response = pds_chat_service.ask_pds_ai(db, message="How many deployments for tenant UNKNOWN?")
    assert response["provider"] == "ollama_rag"


@pytest.mark.parametrize("failed_result", [
    {"ok": False, "error": "Lookup failed"},
    {"ok": True, "result": None},
    {"ok": True, "result": {"error": "Database unavailable"}},
    {"ok": True, "result": {}},
])
def test_direct_failure_falls_back_to_faiss_and_verified_tool_loop(db, monkeypatch, failed_result):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    original = pds_chat_service._run_tool
    tool_calls = []
    retrieval_calls = []

    def tool(session, name, arguments):
        tool_calls.append(name)
        if len(tool_calls) == 1:
            return failed_result
        return original(session, name, arguments)

    def retrieve(session, query):
        retrieval_calls.append(query)
        return "Relevant PDS supporting context"

    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "count_schedules", "arguments": {}}}]}},
        {"message": {"content": "There are no schedules in the verified database."}},
    ])
    monkeypatch.setattr(pds_chat_service, "_run_tool", tool)
    monkeypatch.setattr(pds_rag_service, "retrieve_context", retrieve)
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: next(responses))
    response = pds_chat_service.ask_pds_ai(db, message="How many schedules are there?")
    assert response["provider"] == "ollama_rag"
    assert len(tool_calls) == 2
    assert retrieval_calls == ["How many schedules are there?"]


def test_empty_search_is_valid_and_does_not_call_ai(db, monkeypatch):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: pytest.fail("Empty results are valid"))
    response = pds_chat_service.ask_pds_ai(db, message="Show deployments this month")
    assert response["answer"] == "No matching PDS schedules were found."
    assert response["provider"] == "pds_backend_api"


def test_null_api_result_is_not_success(db, monkeypatch):
    monkeypatch.setattr(pds_api_agent, "execute", lambda *_args: None)
    assert pds_api_agent.handle_tool_call(db, "count_schedules", {})["ok"] is False


def test_embedding_outage_still_allows_verified_database_reasoning(db, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def unavailable(*_args):
        raise HTTPException(502, "Embedding model unavailable")

    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "deployment_summary", "arguments": {}}}]}},
        {"message": {"content": "No deployments exist to analyze."}},
    ])
    monkeypatch.setattr(pds_rag_service, "retrieve_context", unavailable)
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: next(responses))
    response = pds_chat_service.ask_pds_ai(db, message="Explain deployment history")
    assert response["provider"] == "ollama_rag"


@pytest.mark.parametrize("output", [{"ok": False, "error": "Unavailable"}, {"ok": True, "result": None}])
def test_slot_api_failure_reaches_reasoning(db, monkeypatch, output):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")
    monkeypatch.setattr(pds_api_agent, "handle_tool_call", lambda *_args: output)
    monkeypatch.setattr(pds_chat_service, "_ask_via_ollama_rag", lambda *_args: {"provider": "ollama_rag"})
    response = pds_chat_service.ask_pds_ai(db, message="When is the next slot available?")
    assert response["provider"] == "ollama_rag"
