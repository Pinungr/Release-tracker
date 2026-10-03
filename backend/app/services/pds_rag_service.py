"""In-memory FAISS retrieval and local Ollama chat for PDS data."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
import importlib
import threading
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import BookingAssignment, DeploymentBooking, Tenant, User

EMBEDDING_BATCH_SIZE = 64
RETRIEVAL_LIMIT = 6
_INDEX_LOCK = threading.RLock()
_DOCUMENT_VECTORS: OrderedDict = OrderedDict()
DOCUMENT_VECTOR_CACHE_LIMIT = 4096


@dataclass
class _MemoryIndex:
    signature: tuple[int, str, int, str, int, str, int, str]
    documents: list[str]
    index: Any | None


_INDEXES: dict[tuple[int, str, str], _MemoryIndex] = {}


def _libraries():
    try:
        return importlib.import_module("numpy"), importlib.import_module("faiss")
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The local PDS retrieval dependencies are missing. Install the backend requirements.",
        ) from exc


def _post_ollama(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.ai_base_url.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds, trust_env=False) as client:
            response = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "The local AI response timed out. Try a shorter, more specific question.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PDS could not reach the configured local Ollama service.",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Local Ollama request failed with HTTP {response.status_code}. Check that the configured models are available.",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local Ollama service returned an invalid response.",
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local Ollama service returned an invalid response.",
        )
    return body


def _embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[offset : offset + EMBEDDING_BATCH_SIZE]
        body = _post_ollama(
            "/api/embed",
            {"model": settings.ai_embedding_model, "input": batch},
        )
        batch_embeddings = body.get("embeddings")
        if (
            not isinstance(batch_embeddings, list)
            or len(batch_embeddings) != len(batch)
            or any(not isinstance(vector, list) or not vector for vector in batch_embeddings)
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The local embedding model returned invalid vectors.",
            )
        try:
            embeddings.extend([[float(value) for value in vector] for vector in batch_embeddings])
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The local embedding model returned invalid vectors.",
            ) from exc
    return embeddings


def _record_text(booking: DeploymentBooking) -> str:
    managers = sorted(
        assignment.user.full_name
        for assignment in booking.assignments
        if assignment.user is not None
    )
    fields = [
        f"Schedule: {booking.booking_reference}",
        f"Tenant: {booking.tenant_name}",
        f"Deployment date: {booking.deployment_date.isoformat()}",
        f"Slot: {booking.slot_number if booking.slot_number is not None else 'Emergency queue'}",
        f"Emergency: {'yes' if booking.is_emergency else 'no'}",
        f"Status: {booking.status}",
        f"Change number: {booking.change_number or 'not assigned'}",
        f"Jira number: {booking.jira_number or 'not provided'}",
        f"Technology: {booking.technology}",
        f"Environment: {booking.environment}",
        f"Impacted region: {booking.impacted_region}",
        f"Release managers: {', '.join(managers) if managers else 'not assigned'}",
        f"Implementation summary: {booking.implementation_summary[:2000]}",
        f"Deployment description: {booking.deployment_description[:2000]}",
        f"Justification: {booking.justification[:1000]}",
    ]
    if booking.is_emergency and booking.emergency_reason:
        fields.append(f"Emergency reason: {booking.emergency_reason[:1000]}")
    return "\n".join(fields)


def _load_documents(db: Session) -> list[str]:
    bookings = db.scalars(
        select(DeploymentBooking)
        .options(selectinload(DeploymentBooking.assignments).selectinload(BookingAssignment.user))
        .order_by(DeploymentBooking.id.asc())
    ).all()
    tenants = db.scalars(select(Tenant).order_by(Tenant.id.asc())).all()
    documents = [_record_text(booking) for booking in bookings]
    for tenant in tenants:
        details = [
            f"Tenant: {tenant.name}",
            f"Tenant code: {tenant.tenant_code or 'not set'}",
            f"Active: {'yes' if tenant.is_active else 'no'}",
        ]
        if tenant.description:
            details.append(f"Description: {tenant.description[:1000]}")
        documents.append("\n".join(details))
    return documents


def _source_signature(db: Session) -> tuple[int, str, int, str, int, str, int, str]:
    booking_count, booking_updated = db.execute(
        select(func.count(DeploymentBooking.id), func.max(DeploymentBooking.updated_at))
    ).one()
    tenant_count, tenant_updated = db.execute(
        select(func.count(Tenant.id), func.max(Tenant.updated_at))
    ).one()
    assignment_count, assignment_updated = db.execute(
        select(func.count(BookingAssignment.id), func.max(BookingAssignment.assigned_at))
    ).one()
    user_count, user_updated = db.execute(
        select(func.count(User.id), func.max(User.updated_at))
    ).one()
    return (
        int(booking_count),
        booking_updated.isoformat() if booking_updated else "",
        int(tenant_count),
        tenant_updated.isoformat() if tenant_updated else "",
        int(assignment_count),
        assignment_updated.isoformat() if assignment_updated else "",
        int(user_count),
        user_updated.isoformat() if user_updated else "",
    )


def _build_index(documents: list[str], numpy, faiss):
    if not documents:
        return None
    try:
        keys = [(settings.ai_base_url, settings.ai_embedding_model, hashlib.sha256(document.encode()).hexdigest()) for document in documents]
        missing = list(dict.fromkeys(key for key in keys if key not in _DOCUMENT_VECTORS))
        document_by_key = dict(zip(keys, documents))
        fresh = dict(zip(missing, _embed_texts([document_by_key[key] for key in missing]))) if missing else {}
        matrix = numpy.asarray([fresh[key] if key in fresh else _DOCUMENT_VECTORS[key] for key in keys], dtype=numpy.float32)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local embedding model returned vectors with an invalid shape.",
        ) from exc
    if matrix.ndim != 2 or matrix.shape[0] != len(documents) or matrix.shape[1] == 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local embedding model returned vectors with an invalid shape.",
        )
    if not numpy.isfinite(matrix).all():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local embedding model returned non-finite vectors.",
        )
    for key, vector in zip(keys, matrix):
        _DOCUMENT_VECTORS[key] = vector.tolist()
        _DOCUMENT_VECTORS.move_to_end(key)
    while len(_DOCUMENT_VECTORS) > DOCUMENT_VECTOR_CACHE_LIMIT:
        _DOCUMENT_VECTORS.popitem(last=False)
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(int(matrix.shape[1]))
    index.add(matrix)
    return index


def retrieve_context(db: Session, query: str) -> str:
    """Retrieve current PDS records with a process-local FAISS cosine index."""
    numpy, faiss = _libraries()
    key = (id(db.get_bind()), settings.ai_base_url, settings.ai_embedding_model)

    with _INDEX_LOCK:
        signature = _source_signature(db)
        cached = _INDEXES.get(key)
        if cached is None or cached.signature != signature:
            documents = _load_documents(db)
            index = _build_index(documents, numpy, faiss)
            cached = _MemoryIndex(signature, documents, index)
            _INDEXES[key] = cached

        if cached.index is None:
            return ""
        query_vector = numpy.asarray(_embed_texts([query]), dtype=numpy.float32)
        if (
            query_vector.ndim != 2
            or query_vector.shape[0] != 1
            or query_vector.shape[1] != cached.index.d
            or not numpy.isfinite(query_vector).all()
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The local embedding model returned an invalid query vector.",
            )
        faiss.normalize_L2(query_vector)
        scores, matches = cached.index.search(query_vector, min(RETRIEVAL_LIMIT, len(cached.documents)))
        selected: list[str] = []
        for score, match in zip(scores[0], matches[0]):
            if int(match) < 0 or not numpy.isfinite(score):
                continue
            selected.append(cached.documents[int(match)])
        return "\n\n---\n\n".join(selected)


def chat(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    context_window: int | None = None,
) -> dict[str, Any]:
    """Send a non-streaming tool-capable chat request to the local Ollama model."""
    return _post_ollama(
        "/api/chat",
        {
            "model": settings.ai_model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "keep_alive": settings.ai_keep_alive,
            "options": _generation_options(0.2, settings.ai_max_output_tokens, context_window),
        },
    )


def plan(messages: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    """Separate schema-constrained planning request, without tool execution."""
    return _post_ollama("/api/chat", {
        "model": settings.ai_model, "messages": messages, "format": schema,
        "stream": False, "think": False, "keep_alive": settings.ai_keep_alive,
        "options": _generation_options(0, 1024),
    })


def _generation_options(temperature: float, output_tokens: int, context_window: int | None = None) -> dict[str, Any]:
    options = {"temperature": temperature, "num_predict": output_tokens, "num_ctx": context_window or settings.ai_context_window, "num_gpu": 0}
    if settings.ai_num_threads:
        options["num_thread"] = settings.ai_num_threads
    return options
