import json
import pytest
from app.services import pds_query_plan as planner, pds_rag_service
from test_assistant_audit import audit_records


@pytest.fixture(autouse=True)
def isolate_plan_cache(monkeypatch):
    planner._PLAN_CACHE.clear()
    monkeypatch.setattr(planner, "_direct_plan", lambda *_args: None)
    monkeypatch.setattr(planner.settings, "ai_plan_cache_seconds", 0)
    yield
    planner._PLAN_CACHE.clear()


def scope(**kwargs):
    return dict(tenant=None, date_from="2026-09-01", date_to="2026-09-30", status=None, is_emergency=None, **{}) | kwargs


def mock_plan(monkeypatch, operation, scopes):
    monkeypatch.setattr(pds_rag_service, "plan", lambda *_args: {"message": {"content": json.dumps(dict(operation=operation, scopes=scopes, clarification=""))}})


def test_comparison_aggregates_and_scope(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "compare", [scope(status="FAILED"), scope(status="BOOKED")])
    result = planner.answer(db, "Compare failed deployments in September 2026 with booked deployments in September 2026", None)
    assert [row["total"] for row in result["evidence"]] == [1, 2]
    assert "-1 deployments" in result["answer"]
    assert result["query_scope"]["scopes"][0]["status"] == "FAILED"


@pytest.mark.parametrize("bad_scope", [scope(), scope(status="FAILED", is_emergency=False), scope(status="FAILED", is_emergency=True, date_from="2026-10-01", date_to="2026-10-31")])
def test_reject_dropped_constraints(db, audit_records, monkeypatch, bad_scope):
    mock_plan(monkeypatch, "count", [bad_scope])
    result = planner.answer(db, "Count failed emergency deployments in September 2026", None)
    assert "could not verify" in result["answer"]
    assert "evidence" not in result


def test_percentage_computed_from_full_counts(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "percentage", [scope(status="FAILED"), scope()])
    result = planner.answer(db, "What percentage of deployments failed in September 2026?", None)
    assert "25.00%" in result["answer"]


def test_zero_denominator(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "percentage", [scope(status="FAILED", date_from="2026-10-01", date_to="2026-10-31"), scope(date_from="2026-10-01", date_to="2026-10-31")])
    assert "undefined" in planner.answer(db, "What percentage of deployments failed in October 2026?", None)["answer"]


def test_followup_preserves_tenant(db, audit_records, monkeypatch):
    old = dict(operation="count", scopes=[scope(tenant=audit_records.name, status="FAILED")], clarification="")
    mock_plan(monkeypatch, "compare", [scope(status="FAILED"), scope(status="BOOKED")])
    result = planner.answer(db, "Compare those deployments with booked deployments", [{"role": "assistant", "query_scope": old}])
    assert "could not verify" in result["answer"]


def test_reject_missing_second_period(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "compare", [scope(), scope()])
    assert "could not verify" in planner.answer(db, "Compare deployments in September 2026 versus October 2026", None)["answer"]


def test_unsupported_filter_cannot_be_ignored(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "count", [scope()])
    assert "could not verify" in planner.answer(db, "Count deployments by region in September 2026", None)["answer"]

def test_unknown_tenant_does_not_become_global(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "count", [scope()])
    assert "could not verify" in planner.answer(db, "Count deployments for tenant XYZ in September 2026", None)["answer"]


def test_each_requested_status_is_verified(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "compare", [scope(status="FAILED"), scope(status="FAILED")])
    assert "could not verify" in planner.answer(db, "Compare failed and booked deployments in September 2026", None)["answer"]


def test_invalid_percentage_scope_rejected():
    with pytest.raises(ValueError):
        planner.Plan.model_validate(dict(operation="percentage", scopes=[scope(status="FAILED"), scope(status="BOOKED")], clarification=""))


def test_document_embedding_cache_reuses_unchanged_text(monkeypatch):
    import numpy
    from types import SimpleNamespace
    pds_rag_service._DOCUMENT_VECTORS.clear()
    embedded = []
    def embed(texts):
        embedded.append(texts)
        return [[1.0, 0.0] for text in texts]
    monkeypatch.setattr(pds_rag_service, "_embed_texts", embed)
    class Index:
        def __init__(self, dimensions):
            self.d = dimensions
        def add(self, matrix):
            pass
    faiss = SimpleNamespace(normalize_L2=lambda matrix: None, IndexFlatIP=Index)
    try:
        pds_rag_service._build_index(["record A", "record B"], numpy, faiss)
        pds_rag_service._build_index(["record A", "record B changed"], numpy, faiss)
        assert embedded == [["record A", "record B"], ["record B changed"]]
    finally:
        pds_rag_service._DOCUMENT_VECTORS.clear()

def test_unrequested_tenant_filter_is_rejected(db, audit_records, monkeypatch):
    mock_plan(monkeypatch, "percentage", [scope(tenant=audit_records.name, status="FAILED"), scope(tenant=audit_records.name)])
    assert "could not verify" in planner.answer(db, "What percentage of deployments failed in September 2026?", None)["answer"]

def test_cached_plan_requeries_database(db, audit_records, monkeypatch):
    from app.models import DeploymentBooking
    from sqlalchemy import select
    monkeypatch.setattr(planner.settings, "ai_plan_cache_seconds", 300)
    calls = []
    def model(*_args):
        calls.append(1)
        return {"message": {"content": json.dumps(dict(operation="percentage", scopes=[scope(status="FAILED"), scope()], clarification=""))}}
    monkeypatch.setattr(pds_rag_service, "plan", model)
    question = "What percentage of deployments failed in September 2026?"
    first = planner.answer(db, question, None)
    assert first["evidence"][0]["total"] == 1
    row = db.scalar(select(DeploymentBooking).where(DeploymentBooking.booking_reference == "pds-002"))
    row.status = "FAILED"
    db.commit()
    second = planner.answer(db, question, None)
    assert second["evidence"][0]["total"] == 2
    assert len(calls) == 1
