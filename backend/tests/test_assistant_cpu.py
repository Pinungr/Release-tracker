"""CPU execution contracts: preload records, minimize calls, retain verification."""
import pytest
from fastapi import HTTPException
from app.services import pds_chat_service, pds_rag_service
from test_assistant_audit import audit_records


def test_exact_record_reasoning_uses_one_model_call_and_no_vectors(db, audit_records, monkeypatch):
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda *_args: pytest.fail("Exact records do not need vectors"))
    calls = []
    def chat(**kwargs):
        calls.append(kwargs)
        assert kwargs["tools"] == []
        assert kwargs["context_window"] == 4096
        assert '"schedule_no": "pds-001"' in kwargs["messages"][-1]["content"]
        assert len(kwargs["messages"][0]["content"]) < 600
        return {"message": {"content": "PDS-001 is recorded as FAILED; no cause is recorded."}}
    monkeypatch.setattr(pds_rag_service, "chat", chat)
    result = pds_chat_service._ask_via_ollama_rag(db, "Why did PDS-001 fail?", None)
    assert result["evidence"][0]["status"] == "FAILED"
    assert len(calls) == 1


def test_comparison_preloads_both_records(db, audit_records, monkeypatch):
    def chat(**kwargs):
        evidence = kwargs["messages"][-1]["content"]
        assert '"schedule_no": "pds-001"' in evidence
        assert '"schedule_no": "pds-002"' in evidence
        return {"message": {"content": "PDS-001 failed; PDS-002 is booked."}}
    monkeypatch.setattr(pds_rag_service, "chat", chat)
    result = pds_chat_service._ask_via_ollama_rag(db, "Compare PDS-001 and PDS-002", [])
    assert len(result["evidence"]) == 2


def test_incomplete_record_comparison_answer_rejected(db, audit_records, monkeypatch):
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: {"message": {"content": "PDS-001 failed."}})
    with pytest.raises(HTTPException, match="verified explanation"):
        pds_chat_service._ask_via_ollama_rag(db, "Compare PDS-001 and PDS-002", [])


def test_cpu_options_and_thread_override(monkeypatch):
    monkeypatch.setattr(pds_rag_service.settings, "ai_num_threads", 0)
    assert "num_thread" not in pds_rag_service._generation_options(0, 512)
    monkeypatch.setattr(pds_rag_service.settings, "ai_num_threads", 4)
    options = pds_rag_service._generation_options(0, 512, 4096)
    assert options["num_thread"] == 4
    assert options["num_ctx"] == 4096
    assert options["num_gpu"] == 0

def test_explicit_record_question_ignores_unrelated_history(db, audit_records, monkeypatch):
    monkeypatch.setattr(pds_rag_service, "retrieve_context", lambda *_args: pytest.fail("Explicit new record question does not need vectors"))
    monkeypatch.setattr(pds_rag_service, "chat", lambda **_kwargs: {"message": {"content": "PDS-001 is FAILED."}})
    result = pds_chat_service._ask_via_ollama_rag(db, "Why did PDS-001 fail?", [{"role":"user","content":"Show EPCAT deployments"}])
    assert result["evidence"][0]["schedule_no"] == "pds-001"

@pytest.mark.parametrize("question, totals", [
    ("Compare failed deployments in September 2026 with booked deployments in September 2026", [1, 2]),
    ("What percentage of deployments failed in September 2026?", [1, 4]),
])
def test_simple_analytics_bypass_model(db, audit_records, monkeypatch, question, totals):
    from app.services import pds_query_plan
    monkeypatch.setattr(pds_rag_service, "plan", lambda *_args: pytest.fail("Representable comparisons do not need AI"))
    result = pds_query_plan.answer(db, question, None)
    assert [row["total"] for row in result["evidence"]] == totals


def test_ambiguous_period_is_not_parsed_as_global_count():
    from app.services import pds_query_plan
    assert pds_query_plan._direct_plan("Compare failed deployments in the old period with booked deployments in September 2026", [], pds_chat_service) is None
