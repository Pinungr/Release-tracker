"""Shared schedule access (tenant group, collaborators) and Admin/RM unlock of the automatic lock."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from conftest import booking_payload, create_booking, post_booking, sign_up_and_login


def _group_id(admin, *, tenant_id=None, group_type=None) -> int:
    for group in admin.get("/api/admin/groups").json():
        if tenant_id is not None and group["tenant_id"] == tenant_id:
            return group["id"]
        if group_type is not None and group["group_type"] == group_type:
            return group["id"]
    raise AssertionError("group not found")


def _user_id(client) -> int:
    return client.get("/api/auth/me").json()["id"]


def _join(admin, client, group_id: int) -> None:
    response = admin.post(f"/api/admin/groups/{group_id}/members/{_user_id(client)}")
    assert response.status_code == 200, response.text


def _edit(client, booking, **changes):
    payload = booking_payload(
        booking["tenant_id"], date.fromisoformat(booking["deployment_date"]), booking["slot_number"], **changes
    )
    payload.pop("deployment_date")
    payload.pop("slot_number")
    return client.put(f"/api/bookings/{booking['id']}", json=payload)


def _upload(client, booking_id, category, *names):
    return client.post(
        f"/api/bookings/{booking_id}/attachments",
        data={"category": category},
        files=[("file", (name, io.BytesIO(b"data"), "application/octet-stream")) for name in names],
    )


def _lock_everything(admin) -> None:
    """Widen the existing automatic lock window so the test schedules fall inside it."""
    assert admin.put("/api/admin/settings", json={"booking_freeze_dates": 25}).status_code == 200


def _audit(admin, booking_id, event_type):
    return [e for e in admin.get(f"/api/admin/audit?booking_id={booking_id}").json() if e["event_type"] == event_type]


@pytest.fixture
def people(anon, admin, tenant, other_tenant):
    """Tenant A scheduler and colleague, a Tenant B user and a Member Pool user."""
    tenant_a = _group_id(admin, tenant_id=tenant)
    tenant_b = _group_id(admin, tenant_id=other_tenant)
    clients = {name: sign_up_and_login(anon, name) for name in ("scheduler", "colleague", "outsider", "pooluser")}
    _join(admin, clients["scheduler"], tenant_a)
    _join(admin, clients["colleague"], tenant_a)
    _join(admin, clients["outsider"], tenant_b)
    yield clients
    for client in clients.values():
        client.close()


# --------------------------------------------------------------------------- #
# Same-tenant editing
# --------------------------------------------------------------------------- #


def test_same_tenant_user_can_edit_and_other_tenant_cannot(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)

    edited = _edit(people["colleague"], booking, impacted_region="EMEA")
    assert edited.status_code == 200, edited.text
    assert edited.json()["impacted_region"] == "EMEA"
    assert edited.json()["access_basis"] == "TENANT_MEMBER"

    denied = _edit(people["outsider"], booking, impacted_region="LATAM")
    assert denied.status_code == 403
    # Other tenants can still read the record.
    view = people["outsider"].get(f"/api/bookings/{booking['id']}").json()
    assert view["can_edit"] is False and view["can_manage_attachments"] is False

    event = _audit(admin, booking["id"], "BOOKING_EDITED")[0]
    assert event["requester_email"] == "colleague@example.com"
    assert event["actor_access"] == "TENANT_MEMBER"


def test_same_tenant_user_can_cancel_and_reschedule(people, tenant, next_monday):
    first = create_booking(people["scheduler"], tenant, next_monday, 1)
    options = people["colleague"].get(f"/api/bookings/{first['id']}/reschedule-options").json()
    assert options
    moved = people["colleague"].post(
        f"/api/bookings/{first['id']}/reschedule",
        json={"deployment_date": options[0]["deployment_date"], "slot_number": options[0]["slot_number"]},
    )
    assert moved.status_code == 200, moved.text
    cancelled = people["colleague"].request("DELETE", f"/api/bookings/{first['id']}", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_leaving_the_tenant_group_removes_shared_access(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    group = _group_id(admin, tenant_id=tenant)
    assert admin.delete(f"/api/admin/groups/{group}/members/{_user_id(people['colleague'])}").status_code == 200
    assert _edit(people["colleague"], booking, impacted_region="EMEA").status_code == 403


# --------------------------------------------------------------------------- #
# Collaborators
# --------------------------------------------------------------------------- #


def test_member_pool_collaborator_gains_and_loses_edit_access(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    pool_id = _user_id(people["pooluser"])
    assert _edit(people["pooluser"], booking, impacted_region="EMEA").status_code == 403

    candidates = people["scheduler"].get(f"/api/bookings/{booking['id']}/collaborator-candidates?q=pooluser").json()
    assert [c["id"] for c in candidates] == [pool_id]
    # Tenant colleagues already share access and are not offered from the pool.
    listed = {c["id"] for c in people["scheduler"].get(f"/api/bookings/{booking['id']}/collaborator-candidates").json()}
    assert _user_id(people["colleague"]) not in listed

    added = people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [pool_id]})
    assert added.status_code == 200, added.text
    assert [c["user_id"] for c in added.json()["collaborators"]] == [pool_id]

    edited = _edit(people["pooluser"], booking, impacted_region="EMEA")
    assert edited.status_code == 200, edited.text
    assert edited.json()["access_basis"] == "COLLABORATOR"
    assert _upload(people["pooluser"], booking["id"], "SUPPORTING_DOCUMENTS", "notes.pdf").status_code == 200
    # Collaborators never gain Admin/RM rights or delegation rights.
    assert people["pooluser"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []}).status_code == 403
    assert people["pooluser"].post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat()}).status_code == 403

    removed = people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []})
    assert removed.status_code == 200
    assert _edit(people["pooluser"], booking, impacted_region="APAC").status_code == 403

    assert _audit(admin, booking["id"], "COLLABORATOR_ADDED")[0]["new_values"]["collaborator_user_id"] == pool_id
    assert _audit(admin, booking["id"], "COLLABORATOR_REMOVED")[0]["old_values"]["collaborator_user_id"] == pool_id
    collaborator_edit = next(e for e in _audit(admin, booking["id"], "BOOKING_EDITED") if e["actor_access"] == "COLLABORATOR")
    assert collaborator_edit["requester_email"] == "pooluser@example.com"


def test_collaborators_come_from_the_member_pool_and_only_the_scheduler_manages_them(people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    outsider = _user_id(people["outsider"])
    rejected = people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [outsider]})
    assert rejected.status_code == 422
    assert people["colleague"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []}).status_code == 403
    assert people["colleague"].get(f"/api/bookings/{booking['id']}/collaborator-candidates").status_code == 403


# --------------------------------------------------------------------------- #
# Automatic lock + Admin/RM unlock
# --------------------------------------------------------------------------- #


def test_unlock_lets_tenant_and_collaborator_edit_until_the_lock_is_restored(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [_user_id(people["pooluser"])]})
    _lock_everything(admin)

    for client in (people["colleague"], people["pooluser"], admin):
        assert _edit(client, booking, impacted_region="EMEA").status_code == 423
    assert people["colleague"].get(f"/api/bookings/{booking['id']}").json()["lock_reason"] == "AUTOMATIC_DATE_FREEZE"

    unlocked = admin.post(
        "/api/admin/lock-overrides",
        json={"override_date": next_monday.isoformat(), "slot_number": 1, "reason": "Vendor window moved"},
    )
    assert unlocked.status_code == 201, unlocked.text
    detail = people["colleague"].get(f"/api/bookings/{booking['id']}").json()
    assert detail["can_edit"] is True and detail["lock_overridden"] is True
    for client in (people["colleague"], people["pooluser"], admin):
        assert _edit(client, booking, impacted_region="EMEA").status_code == 200

    event = _audit(admin, booking["id"], "AUTOMATIC_LOCK_UNLOCKED")[0]
    assert event["admin_username"] == "testadmin"
    assert event["override_reason"] == "Vendor window moved"
    assert event["new_values"]["slot_number"] == 1

    assert admin.delete(f"/api/admin/lock-overrides/{next_monday.isoformat()}?slot_number=1").status_code == 204
    assert _edit(people["colleague"], booking, impacted_region="APAC").status_code == 423
    assert _audit(admin, booking["id"], "AUTOMATIC_LOCK_RESTORED")[0]["new_values"]["restored_by"] == "testadmin"


def test_locked_and_frozen_needs_both_controls_cleared(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    assert admin.post("/api/admin/slot-freezes", json={"freeze_date": next_monday.isoformat(), "slot_number": 1}).status_code == 200
    _lock_everything(admin)

    assert admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 1}).status_code == 201
    # Unlock never unfreezes: the tenant is still blocked by the manual freeze.
    blocked = _edit(people["colleague"], booking, impacted_region="EMEA")
    assert blocked.status_code == 423
    assert "manually frozen" in blocked.json()["detail"].lower()
    assert people["colleague"].get(f"/api/bookings/{booking['id']}").json()["lock_reason"] == "MANUAL_SLOT_FREEZE"

    assert admin.delete(f"/api/admin/slot-freezes/{next_monday.isoformat()}/1").status_code == 204
    assert _edit(people["colleague"], booking, impacted_region="EMEA").status_code == 200

    # Unfreezing never removed the unlock, and restoring the lock never touches freezes.
    assert admin.delete(f"/api/admin/lock-overrides/{next_monday.isoformat()}?slot_number=1").status_code == 204
    assert _edit(people["colleague"], booking, impacted_region="APAC").status_code == 423


def test_admin_cannot_edit_locked_and_frozen_until_unlocked(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    admin.post("/api/admin/slot-freezes", json={"freeze_date": next_monday.isoformat(), "slot_number": 1})
    _lock_everything(admin)
    assert _edit(admin, booking, impacted_region="EMEA").status_code == 423
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 1})
    # Unlocked + frozen: Admin/RM keep their existing audited freeze override.
    assert _edit(admin, booking, impacted_region="EMEA").status_code == 200


def test_unlocking_one_slot_leaves_other_slots_and_dates_locked(admin, people, tenant, next_monday):
    first = create_booking(people["scheduler"], tenant, next_monday, 1)
    second = create_booking(people["scheduler"], tenant, next_monday, 2)
    _lock_everything(admin)
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 1})
    assert _edit(people["colleague"], first, impacted_region="EMEA").status_code == 200
    assert _edit(people["colleague"], second, impacted_region="EMEA").status_code == 423

    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    day = next(d for d in board["days"] if d["day"] == next_monday.isoformat())
    assert day["automatic_lock"] is True and day["date_unlocked"] is False
    assert {s["slot_number"]: s["lock_override"] for s in day["slots"]}[1] == "SLOT"
    assert {s["slot_number"]: s["lock_override"] for s in day["slots"]}[2] is None

    # A whole-date unlock covers every slot on that date.
    assert admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat()}).status_code == 201
    assert _edit(people["colleague"], second, impacted_region="EMEA").status_code == 200


def test_unlocked_free_slot_can_be_booked_by_a_tenant(admin, people, tenant, next_monday):
    _lock_everything(admin)
    assert post_booking(people["scheduler"], booking_payload(tenant, next_monday, 3)).status_code == 423
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 3})
    assert post_booking(people["scheduler"], booking_payload(tenant, next_monday, 3)).status_code == 201


def test_unlock_rules(admin, people, tenant, next_monday):
    day = next_monday.isoformat()
    assert admin.post("/api/admin/lock-overrides", json={"override_date": day}).status_code == 409  # not locked
    _lock_everything(admin)
    assert people["scheduler"].post("/api/admin/lock-overrides", json={"override_date": day}).status_code == 403
    assert admin.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 1}).status_code == 201
    assert admin.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 1}).status_code == 409
    assert people["scheduler"].delete(f"/api/admin/lock-overrides/{day}?slot_number=1").status_code == 403
    assert admin.delete(f"/api/admin/lock-overrides/{day}?slot_number=2").status_code == 404  # never unlocked
    other = (next_monday + timedelta(days=1)).isoformat()
    assert admin.delete(f"/api/admin/lock-overrides/{other}").status_code == 404


def _day(admin, day):
    board = admin.get(f"/api/schedule?week={day.isoformat()}").json()
    return next(d for d in board["days"] if d["day"] == day.isoformat())


def test_whole_date_unlock_absorbs_slot_unlocks_and_restore_relocks_every_slot(admin, people, tenant, next_monday):
    day = next_monday.isoformat()
    _lock_everything(admin)
    admin.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 2})
    assert admin.post("/api/admin/lock-overrides", json={"override_date": day}).status_code == 201
    assert all(s["lock_override"] == "DATE" for s in _day(admin, next_monday)["slots"])
    # Slot unlocks are absorbed while the whole date is unlocked.
    assert admin.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 3}).status_code == 409

    assert admin.delete(f"/api/admin/lock-overrides/{day}").status_code == 204
    view = _day(admin, next_monday)
    assert view["date_unlocked"] is False
    assert all(s["lock_override"] is None for s in view["slots"])
    unlocked = next(
        e for e in admin.get("/api/admin/audit").json()
        if e["event_type"] == "AUTOMATIC_LOCK_UNLOCKED" and e["new_values"].get("replaced_slot_unlocks")
    )
    assert unlocked["new_values"]["replaced_slot_unlocks"] == [2]


def test_restoring_a_date_also_clears_leftover_slot_unlocks(admin, people, tenant, next_monday, db):
    """Defensive: slot rows left beside a date row (e.g. from before this rule) are cleared too."""
    from app.models import AutomaticLockOverride

    _lock_everything(admin)
    db.add_all([
        AutomaticLockOverride(override_date=next_monday, slot_number=None),
        AutomaticLockOverride(override_date=next_monday, slot_number=1),
    ])
    db.commit()
    assert admin.delete(f"/api/admin/lock-overrides/{next_monday.isoformat()}").status_code == 204
    db.expire_all()
    assert db.query(AutomaticLockOverride).count() == 0
    event = next(e for e in admin.get("/api/admin/audit").json() if e["event_type"] == "AUTOMATIC_LOCK_RESTORED")
    assert event["old_values"]["slot_unlocks_removed"] == [1]


def test_whole_date_unlock_opens_the_emergency_queue(admin, tenant, next_monday):
    _lock_everything(admin)
    assert _day(admin, next_monday)["emergency_open"] is False
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat()})
    assert _day(admin, next_monday)["emergency_open"] is True


def test_tenant_can_reschedule_into_an_unlocked_slot_only(admin, people, tenant, next_monday):
    # Beyond the widened lock window, so only the destination is locked.
    booking = create_booking(people["scheduler"], tenant, next_monday + timedelta(days=49), 1)
    _lock_everything(admin)
    target = {"deployment_date": next_monday.isoformat(), "slot_number": 3}
    assert people["colleague"].post(f"/api/bookings/{booking['id']}/reschedule", json=target).status_code == 423
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 3})
    moved = people["colleague"].post(f"/api/bookings/{booking['id']}/reschedule", json=target)
    assert moved.status_code == 200, moved.text


# --------------------------------------------------------------------------- #
# Scheduler outside the tenant group, completed schedules, attachments under locks
# --------------------------------------------------------------------------- #


def test_scheduler_keeps_access_after_leaving_the_tenant_group(admin, people, tenant, other_tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    scheduler_id = _user_id(people["scheduler"])
    admin.delete(f"/api/admin/groups/{_group_id(admin, tenant_id=tenant)}/members/{scheduler_id}")
    admin.post(f"/api/admin/groups/{_group_id(admin, tenant_id=other_tenant)}/members/{scheduler_id}")

    edited = _edit(people["scheduler"], booking, impacted_region="EMEA")
    assert edited.status_code == 200, edited.text
    assert edited.json()["access_basis"] == "SCHEDULER"
    assert _upload(people["scheduler"], booking["id"], "SUPPORTING_DOCUMENTS", "a.pdf").status_code == 200
    assert people["scheduler"].request("DELETE", f"/api/bookings/{booking['id']}", json={}).status_code == 200


def _complete(admin, anon, booking):
    rm = sign_up_and_login(anon, "closer")
    _join(admin, rm, _group_id(admin, group_type="RELEASE_MANAGERS"))
    admin.post(f"/api/admin/bookings/{booking['id']}/assign-users", json={"user_ids": [_user_id(rm)]})
    assert rm.post(f"/api/bookings/{booking['id']}/start-work", json={"change_number": "CHG-1"}).status_code == 200
    done = admin.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "COMPLETED"})
    assert done.status_code == 200, done.text


def test_completed_schedule_is_read_only_except_for_admin(anon, admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [_user_id(people["pooluser"])]})
    _complete(admin, anon, booking)

    for client in (people["scheduler"], people["colleague"], people["pooluser"]):
        assert _edit(client, booking, impacted_region="EMEA").status_code == 400
        assert _upload(client, booking["id"], "SUPPORTING_DOCUMENTS", "late.pdf").status_code == 400
        view = client.get(f"/api/bookings/{booking['id']}").json()
        flags = ("can_edit", "can_cancel", "can_reschedule", "can_manage_attachments", "can_manage_collaborators")
        assert not any(view[k] for k in flags)
    assert people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []}).status_code == 400

    # Direct API cancellation is refused for everyone, including Admin/RM.
    for client in (people["scheduler"], admin):
        cancelled = client.request("DELETE", f"/api/bookings/{booking['id']}", json={})
        assert cancelled.status_code == 400
        assert "completed" in cancelled.json()["detail"].lower()
    assert admin.post(f"/api/admin/bookings/{booking['id']}/status", json={"status": "CANCELLED"}).status_code == 400

    # Admin/RM can still correct details and attach missing paperwork.
    assert _edit(admin, booking, impacted_region="EMEA").status_code == 200
    assert _upload(admin, booking["id"], "SUPPORTING_DOCUMENTS", "signoff.pdf").status_code == 200


def test_attachments_follow_lock_and_freeze_for_tenant_and_collaborator(admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [_user_id(people["pooluser"])]})
    uploaded = _upload(people["scheduler"], booking["id"], "SUPPORTING_DOCUMENTS", "a.pdf", "b.pdf")
    ids = [a["id"] for a in uploaded.json()["attachments"] if a["category"] == "SUPPORTING_DOCUMENTS"]
    _lock_everything(admin)
    admin.post("/api/admin/slot-freezes", json={"freeze_date": next_monday.isoformat(), "slot_number": 1})

    def blocked(client):
        return (
            _upload(client, booking["id"], "SUPPORTING_DOCUMENTS", "c.pdf").status_code == 423
            and client.delete(f"/api/bookings/{booking['id']}/attachments/{ids[0]}").status_code == 423
            and client.post(
                f"/api/bookings/{booking['id']}/attachments/bulk-delete", json={"attachment_ids": ids}
            ).status_code == 423
        )

    # Locked + frozen, then unlocked + frozen: the tenant side stays blocked.
    assert all(blocked(c) for c in (people["colleague"], people["pooluser"]))
    admin.post("/api/admin/lock-overrides", json={"override_date": next_monday.isoformat(), "slot_number": 1})
    assert all(blocked(c) for c in (people["colleague"], people["pooluser"]))

    # Admin/RM act through the freeze with the same audited override reason as edits.
    assert admin.delete(f"/api/bookings/{booking['id']}/attachments/{ids[0]}").status_code == 200
    event = _audit(admin, booking["id"], "DOCUMENT_DELETED")[0]
    assert event["override_reason"] == "Administrator override: manually frozen deployment slot."
    assert event["old_values"]["attachment_id"] == ids[0]

    admin.delete(f"/api/admin/slot-freezes/{next_monday.isoformat()}/1")
    assert _upload(people["pooluser"], booking["id"], "SUPPORTING_DOCUMENTS", "c.pdf").status_code == 200


# --------------------------------------------------------------------------- #
# Collaborator management edge cases
# --------------------------------------------------------------------------- #


def test_an_existing_collaborator_who_left_the_pool_stays_listed_and_removable(admin, people, tenant, other_tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    pool_id = _user_id(people["pooluser"])
    people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [pool_id]})
    _join(admin, people["pooluser"], _group_id(admin, tenant_id=other_tenant))  # no longer in the Member Pool

    listed = people["scheduler"].get(f"/api/bookings/{booking['id']}/collaborator-candidates").json()
    assert next(c for c in listed if c["id"] == pool_id)["selected"] is True
    kept = people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [pool_id]})
    assert kept.status_code == 200
    removed = people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []})
    assert removed.status_code == 200 and removed.json()["collaborators"] == []


def test_collaborators_cannot_be_managed_on_emergency_or_cancelled_schedules(admin, people, tenant, next_monday):
    import json

    from conftest import REQUIRED_BOOKING_DOCUMENTS, emergency_payload

    files = [(f"document_{k}", (n, c, "application/octet-stream")) for k, (n, c) in REQUIRED_BOOKING_DOCUMENTS.items()]
    emergency = admin.post(
        "/api/bookings", data={"payload": json.dumps(emergency_payload(tenant, next_monday))}, files=files
    ).json()["booking"]
    assert admin.put(f"/api/bookings/{emergency['id']}/collaborators", json={"user_ids": []}).status_code == 400
    assert admin.get(f"/api/bookings/{emergency['id']}").json()["can_manage_collaborators"] is False

    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    people["scheduler"].request("DELETE", f"/api/bookings/{booking['id']}", json={})
    assert people["scheduler"].put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []}).status_code == 400


# --------------------------------------------------------------------------- #
# Management
# --------------------------------------------------------------------------- #


def test_management_stays_read_only_even_with_tenant_or_rm_membership(anon, admin, people, tenant, next_monday):
    booking = create_booking(people["scheduler"], tenant, next_monday, 1)
    manager = sign_up_and_login(anon, "manager")
    _join(admin, manager, _group_id(admin, group_type="MANAGEMENT"))
    _join(admin, manager, _group_id(admin, tenant_id=tenant))
    rm_manager = sign_up_and_login(anon, "rmmanager")
    _join(admin, rm_manager, _group_id(admin, group_type="RELEASE_MANAGERS"))
    _join(admin, rm_manager, _group_id(admin, group_type="MANAGEMENT"))
    day = next_monday.isoformat()

    for client in (manager, rm_manager):
        assert _edit(client, booking, impacted_region="EMEA").status_code == 403
        assert post_booking(client, booking_payload(tenant, next_monday, 2)).status_code == 403
        assert client.put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": []}).status_code == 403
        assert client.post("/api/admin/slot-freezes", json={"freeze_date": day, "slot_number": 3}).status_code == 403
        assert client.delete(f"/api/admin/slot-freezes/{day}/3").status_code == 403
        assert client.post("/api/admin/lock-overrides", json={"override_date": day}).status_code == 403
        # Intended read access remains.
        assert client.get(f"/api/bookings/{booking['id']}").status_code == 200
        assert client.get("/api/bookings/search?q=pds").status_code == 200
        assert client.get("/api/admin/audit").status_code == 200


# --------------------------------------------------------------------------- #
# Role x action matrix
# --------------------------------------------------------------------------- #

ROLES = ["admin", "release_manager", "same_tenant", "collaborator", "other_tenant", "management"]
ALLOWED = {"admin", "release_manager", "same_tenant", "collaborator"}
PRIVILEGED = {"admin", "release_manager"}


@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix(role, anon, admin, people, tenant, next_monday):
    scheduler = people["scheduler"]
    if role == "admin":
        client = admin
    elif role == "release_manager":
        client = sign_up_and_login(anon, "releasemgr")
        _join(admin, client, _group_id(admin, group_type="RELEASE_MANAGERS"))
    elif role == "same_tenant":
        client = people["colleague"]
    elif role == "collaborator":
        client = people["pooluser"]
    elif role == "other_tenant":
        client = people["outsider"]
    else:
        client = sign_up_and_login(anon, "manager")
        _join(admin, client, _group_id(admin, group_type="MANAGEMENT"))

    booking = create_booking(scheduler, tenant, next_monday, 1)
    scheduler.put(f"/api/bookings/{booking['id']}/collaborators", json={"user_ids": [_user_id(people["pooluser"])]})
    bid = booking["id"]
    may = role in ALLOWED

    assert (_edit(client, booking, impacted_region="EMEA").status_code == 200) is may
    uploaded = _upload(client, bid, "SUPPORTING_DOCUMENTS", "a.sql", "b.sql", "c.sql")
    assert (uploaded.status_code == 200) is may
    if not may:
        _upload(scheduler, bid, "SUPPORTING_DOCUMENTS", "a.sql", "b.sql", "c.sql")
    files = [a["id"] for a in scheduler.get(f"/api/bookings/{bid}").json()["attachments"] if a["category"] == "SUPPORTING_DOCUMENTS"]
    assert (client.delete(f"/api/bookings/{bid}/attachments/{files[0]}").status_code == 200) is may
    assert (client.post(f"/api/bookings/{bid}/attachments/bulk-delete", json={"attachment_ids": files[1:]}).status_code == 200) is may

    options = scheduler.get(f"/api/bookings/{bid}/reschedule-options").json()
    rescheduled = client.post(f"/api/bookings/{bid}/reschedule", json={"deployment_date": options[0]["deployment_date"], "slot_number": options[0]["slot_number"]})
    assert (rescheduled.status_code == 200) is may
    assert (client.request("DELETE", f"/api/bookings/{bid}", json={}).status_code == 200) is may

    _lock_everything(admin)
    day = next_monday.isoformat()
    assert (client.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 2}).status_code == 201) is (role in PRIVILEGED)
    if role not in PRIVILEGED:
        admin.post("/api/admin/lock-overrides", json={"override_date": day, "slot_number": 2})
    assert (client.delete(f"/api/admin/lock-overrides/{day}?slot_number=2").status_code == 204) is (role in PRIVILEGED)
    assert (client.get("/api/admin/document-types").status_code == 200) is (role in PRIVILEGED)
    created = client.post("/api/admin/document-types", json={"label": f"Runbook {role}"})
    assert (created.status_code == 201) is (role in PRIVILEGED)
