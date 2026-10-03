"""Account counts use group membership and never inherit deployment filters."""
import pytest
from sqlalchemy import select

from app.models import GroupMembership, GroupType, User
from app.services import assistant_service, group_service, pds_chat_service, pds_rag_service


@pytest.mark.parametrize("question", [
    "how many management users are there", "Count Management members",
    "How many users are in the Management group?",
])
def test_management_count_is_direct_even_after_deployment_questions(db, monkeypatch, question):
    monkeypatch.setattr(pds_chat_service.settings, "ai_provider", "ollama_rag")

    def forbidden(*_args, **_kwargs):
        pytest.fail("User counts must not call AI or retrieve deployment context")

    monkeypatch.setattr(pds_rag_service, "chat", forbidden)
    monkeypatch.setattr(pds_rag_service, "retrieve_context", forbidden)
    result = pds_chat_service.ask_pds_ai(db, message=question, history=[
        {"role": "user", "content": "Show EPCAT deployments in September 2026"},
        {"role": "assistant", "content": "No matching deployments."},
    ])
    assert result["answer"] == "There are 0 users in the Management group."
    assert result["provider"] == "pds_backend_api"


def test_user_counts_follow_memberships_and_active_filter(db, user, other_user):
    management = group_service.system_group(db, GroupType.MANAGEMENT.value)
    first = db.scalar(select(User).where(User.username == "pinaki"))
    second = db.scalar(select(User).where(User.username == "user2"))
    second.is_active = False
    for account in (first, second):
        db.add(GroupMembership(group_id=management.id, user_id=account.id))
    db.commit()
    result = assistant_service.count_users(db, group="management")
    assert result == {"group": "Management", "total": 2, "active": 1, "inactive": 1, "active_only": False}
    assert assistant_service.count_users(db, group="MANAGEMENT", active_only=True)["total"] == 1
    assert assistant_service.count_users(db)["total"] == 3
    assert "users" not in result  # No personal account details are returned.


def test_count_users_api_requires_authentication(anon):
    assert anon.get("/api/assistant/users/count").status_code == 401


def test_count_users_api_and_chat_agree(admin):
    assert admin.put("/api/admin/ai-access", json={"ai_enabled": True}).status_code == 200
    count = admin.get("/api/assistant/users/count", params={"group": "Management"})
    assert count.status_code == 200
    assert count.json()["total"] == 0
    chat = admin.post("/api/assistant/chat", json={"message": "how many management users are there"})
    assert chat.status_code == 200
    assert chat.json()["answer"] == "There are 0 users in the Management group."
