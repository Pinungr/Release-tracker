"""Concurrency protection for normal deployment slots.

The guarantee comes from the partial unique index on
(deployment_date, slot_number) for non-cancelled, non-emergency rows — not
from a check-then-insert — so it holds when requests arrive simultaneously.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import (
    authenticated,
    booking_payload,
    create_tenant,
    emergency_payload,
    login,
    post_booking,
    register,
)


def test_simultaneous_requests_cannot_double_book_one_slot(anon, admin, next_monday):
    """Eight people race for the same slot; exactly one must win."""
    tenants = [create_tenant(admin, f"Tenant{i}", f"TEN{i}") for i in range(8)]
    clients = []
    for i in range(8):
        register(anon, f"racer{i}")
        clients.append(authenticated(login(anon, f"racer{i}")))

    def attempt(index: int) -> int:
        return post_booking(
            clients[index], booking_payload(tenants[index], next_monday, 2)
        ).status_code

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(attempt, range(8)))
    finally:
        for client in clients:
            client.close()

    assert statuses.count(201) == 1, statuses
    assert statuses.count(500) == 0, "slot contention must surface as 409, never a server error"
    assert all(s in (201, 409) for s in statuses), statuses

    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    booked = [s for s in board["days"][0]["slots"] if s["booking"] is not None]
    assert len(booked) == 1


def test_booking_references_stay_unique_under_contention(anon, admin, next_monday):
    tenants = [create_tenant(admin, f"Ten{i}", f"T{i}") for i in range(4)]
    clients = []
    for i in range(4):
        register(anon, f"writer{i}")
        clients.append(authenticated(login(anon, f"writer{i}")))

    def attempt(index: int) -> dict:
        response = post_booking(
            clients[index], booking_payload(tenants[index], next_monday, index + 1)
        )
        return {"status": response.status_code, "body": response.json()}

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
    finally:
        for client in clients:
            client.close()

    created = [r["body"]["booking"]["booking_reference"] for r in results if r["status"] == 201]
    assert len(created) == 4, [r["status"] for r in results]
    assert len(set(created)) == 4, created


def test_concurrent_emergency_changes_all_succeed(admin, tenant, next_monday):
    """Emergency changes are a queue: contention on a date is not a conflict."""

    def attempt(index: int) -> int:
        return post_booking(admin, emergency_payload(tenant, next_monday, jira_number=f"CHG07770{index}")).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(attempt, range(5)))

    assert statuses == [201] * 5, statuses
    board = admin.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    assert len(board["days"][0]["emergency_bookings"]) == 5
