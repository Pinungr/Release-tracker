"""Regression coverage for clean global and per-schedule audit page APIs."""
from __future__ import annotations

from conftest import create_booking


def test_schedule_can_be_opened_by_human_reference(admin, user, anon, tenant, next_monday):
    booking = create_booking(admin, tenant, next_monday, 1)

    direct = user.get(f"/api/bookings/by-reference/{booking['booking_reference'].upper()}")
    assert direct.status_code == 200, direct.text
    assert direct.json()['id'] == booking['id']
    assert direct.json()['booking_reference'] == booking['booking_reference']

    assert anon.get(f"/api/bookings/by-reference/{booking['booking_reference']}").status_code == 401


def test_global_audit_supports_search_filters_and_pagination(admin, tenant, next_monday):
    booking = create_booking(admin, tenant, next_monday, 1)
    reference = booking['booking_reference']

    searched = admin.get('/api/admin/audit', params={'q': reference}).json()
    assert searched
    assert all(reference in (row['booking_reference'] or '') or reference in str(row).lower() for row in searched)

    created = admin.get('/api/admin/audit', params={'event_type': 'BOOKING_CREATED'}).json()
    assert created
    assert all(row['event_type'] == 'BOOKING_CREATED' for row in created)

    performed_by_admin = admin.get('/api/admin/audit', params={'actor_type': 'ADMIN'}).json()
    assert performed_by_admin
    assert all(row['actor_type'] == 'ADMIN' for row in performed_by_admin)

    newest = admin.get('/api/admin/audit', params={'limit': 1}).json()
    assert len(newest) == 1
    older = admin.get('/api/admin/audit', params={'limit': 10, 'before_id': newest[0]['id']}).json()
    assert all(row['id'] < newest[0]['id'] for row in older)
