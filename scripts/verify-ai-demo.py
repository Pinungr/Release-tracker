"""Read-only live checks for the seeded AI demo; run inside the app container."""
import re

from app.database import SessionLocal
from app.services import pds_chat_service, pds_rag_service


CASES = [
    ("How many schedules are there?", "There are 12 schedules."),
    ("How many failed deployments in September 2026?", "2"),
    ("How many open deployments in October 2026?", "6"),
    ("How many emergency deployments in October 2026?", "1"),
    ("Deployment summary of failed schedules in September 2026", "2"),
    ("Show inactive tenants", "No inactive tenants"),
    ("how many management users are there", "There are 0 users in the Management group."),
    ("How many inactive users are there?", "There are 0 inactive users in PDS."),
    ("How many users are there?", "There is 1 user in PDS."),
    ("How many normal deployments in October 2026?", "5"),
    ("How many EPCAT deployments in September 2026?", "2"),
]


with SessionLocal() as db:
    for question, expected in CASES:
        response = pds_chat_service.ask_pds_ai(db, message=question)
        if expected.isdigit():
            assert re.match(rf"^(?:There (?:are|is) )?{expected}\b", response["answer"]), (question, response["answer"])
        else:
            assert response["answer"].startswith(expected), (question, response["answer"])
        assert response["provider"] == "pds_backend_api"
        print("PASS: " + question, flush=True)
    emergency = pds_chat_service.ask_pds_ai(db, message="Show emergency deployments in October 2026")
    assert set(re.findall(r"pds-\d+", emergency["answer"], re.IGNORECASE)) == {"pds-012"}
    print("PASS: emergency-only search", flush=True)
    context = pds_rag_service.retrieve_context(db, "Provider catalogue refresh failed due to storage permissions")
    assert "SAMPLE DATA" in context
    print("PASS: live FAISS retrieval", flush=True)
    answer = pds_chat_service.ask_pds_ai(db, message="Compare PDS-002 and PDS-005. Verify both schedules and explain the difference in two sentences.")
    assert "permission" in answer["answer"].lower()
    assert "pds-002" in answer["answer"].lower() and "pds-005" in answer["answer"].lower()
    print("PASS: verified two-record comparison", flush=True)
    print("Comparison: " + answer["answer"], flush=True)
    answer = pds_chat_service.ask_pds_ai(db, message="How many of those are there?", history=[
        {"role": "user", "content": "Show failed deployments in September 2026"},
        {"role": "assistant", "content": "PDS-002 and PDS-004 are failed deployments in September 2026."},
    ])
    assert re.search(r"\b(?:2|two)\b", answer["answer"], re.IGNORECASE), answer["answer"]
    assert "RADA" not in answer["answer"] and "EPCAT" not in answer["answer"], answer["answer"]
    print("PASS: contextual follow-up", flush=True)
    print("Follow-up: " + answer["answer"], flush=True)
