"""Small read-only latency sample; not a concurrency or accuracy benchmark."""
import json
from time import perf_counter
from app.database import SessionLocal
from app.services import pds_chat_service, pds_rag_service

original = pds_rag_service._post_ollama
stats = []
def timed_request(path, payload):
    result = original(path, payload)
    stats.append({"endpoint": path, "load_s": round(result.get("load_duration", 0) / 1e9, 3), "prompt_s": round(result.get("prompt_eval_duration", 0) / 1e9, 3), "generation_s": round(result.get("eval_duration", 0) / 1e9, 3), "generated_tokens": result.get("eval_count", 0)})
    return result
pds_rag_service._post_ollama = timed_request
cases = [
    ("direct", "How many schedules are there?"),
    ("direct_repeat", "How many schedules are there?"),
    ("comparison", "Compare EPCAT failed deployments in September 2026 with EPCAT booked deployments in October 2026"),
    ("comparison_repeat", "Compare EPCAT failed deployments in September 2026 with EPCAT booked deployments in October 2026"),
    ("percentage", "What percentage of deployments failed in September 2026?"),
    ("explanation", "Why did PDS-002 fail? Answer in one sentence."),
]
with SessionLocal() as db:
    for name, question in cases:
        stats.clear()
        started = perf_counter()
        try:
            result = pds_chat_service.ask_pds_ai(db, message=question)
            print(json.dumps({"case": name, "seconds": round(perf_counter() - started, 3), "provider": result["provider"], "answer": result["answer"], "ollama": stats}), flush=True)
        except Exception as exc:
            print(json.dumps({"case": name, "seconds": round(perf_counter() - started, 3), "error": str(exc), "ollama": stats}), flush=True)
