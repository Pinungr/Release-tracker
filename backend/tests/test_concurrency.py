"""Concurrency protection: one slot, many simultaneous requesters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import booking_payload


def test_simultaneous_requests_cannot_double_book_one_slot(client, next_monday):
    """Eight threads race for the same slot; exactly one must win.

    The guarantee comes from the partial unique index on
    (deployment_date, slot_number), not from an availability check, so it holds
    even when every request passes validation at the same instant.
    """
    tenants = [f"Tenant{i}" for i in range(8)]

    def attempt(tenant: str) -> int:
        return client.post(
            "/api/bookings",
            json=booking_payload(
                next_monday, 2, tenant_name=tenant, requester_email=f"{tenant.lower()}@example.com"
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, tenants))

    assert statuses.count(201) == 1, statuses
    assert all(s in (201, 409, 500) for s in statuses), statuses
    assert statuses.count(500) == 0, "slot contention must surface as 409, never a server error"

    schedule = client.get(f"/api/schedule?week={next_monday.isoformat()}").json()
    booked = [s for s in schedule["days"][0]["slots"] if s["booking"] is not None]
    assert len(booked) == 1


def test_booking_references_stay_unique_under_contention(client, next_monday):
    def attempt(slot: int) -> dict:
        response = client.post(
            "/api/bookings",
            json=booking_payload(
                next_monday,
                slot,
                tenant_name=f"Tenant{slot}",
                requester_email=f"tenant{slot}@example.com",
            ),
        )
        return {"status": response.status_code, "body": response.json()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, [1, 2, 3, 4]))

    created = [r["body"]["booking"]["booking_reference"] for r in results if r["status"] == 201]
    assert len(created) == 4
    assert len(set(created)) == 4, created
