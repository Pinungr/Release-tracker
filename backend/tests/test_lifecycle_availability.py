from datetime import date, timedelta

import pytest

from conftest import booking_payload, create_booking, promote_to_release_manager
from app.models import DeploymentBooking


def test_completion_requires_start_then_blocks_every_move(admin, user, other_user, tenant, next_monday):
    booking = create_booking(user, tenant, next_monday, 1)
    bid = booking['id']
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(f'/api/admin/bookings/{bid}/assign-users', json={'user_ids': [rm_id]}).status_code == 200
    for client in (admin, other_user):
        denied = client.post(f'/api/admin/bookings/{bid}/status', json={'status': 'COMPLETED', 'override_reason': 'Cannot bypass start'})
        assert denied.status_code == 400
        assert 'Start the task' in denied.json()['detail']
    assert other_user.post(f'/api/bookings/{bid}/start-work', json={'change_number': 'CHG-123'}).status_code == 200
    done = other_user.post(f'/api/admin/bookings/{bid}/status', json={'status': 'COMPLETED'})
    assert done.status_code == 200, done.text
    for client in (admin, user, other_user):
        detail = client.get(f'/api/bookings/{bid}').json()
        assert not detail['can_reschedule']
        assert not detail['can_start_work']
        assert client.get(f'/api/bookings/{bid}/reschedule-options').json() == []
        response = client.post(f'/api/bookings/{bid}/reschedule', json={'deployment_date': str(next_monday), 'slot_number': 2})
        assert response.status_code == 400, response.text
    assert admin.post(f'/api/admin/bookings/{bid}/move', json={'deployment_date': str(next_monday), 'slot_number': 2}).status_code == 400
    assert user.put(f'/api/bookings/{bid}', json=booking_payload(tenant, next_monday, 2)).status_code == 400
    assert admin.post(f'/api/admin/bookings/{bid}/status', json={'status': 'BOOKED'}).status_code == 400
    assert other_user.post(f'/api/bookings/{bid}/start-work', json={'change_number': 'CHG-456'}).status_code == 400
    assert user.get(f'/api/bookings/{bid}').json()['slot_number'] == 1


@pytest.mark.parametrize('missing', ['change_number', 'work_started_at'])
def test_incomplete_start_cannot_be_completed(admin, user, tenant, next_monday, db, missing):
    booking = create_booking(user, tenant, next_monday, 1)
    row = db.get(DeploymentBooking, booking['id'])
    row.status = 'IN_PROGRESS'
    row.change_number = 'CHG-123'
    from app.utils.dates import now_utc
    row.work_started_at = now_utc()
    setattr(row, missing, None)
    db.commit()
    assert admin.post(f"/api/admin/bookings/{row.id}/status", json={'status': 'COMPLETED'}).status_code == 400


def _landing(client) -> dict:
    """What a tenant sees on sign-in."""
    return client.get('/api/schedule?first_available=true').json()


def _fill_week_directly(db, tenant_id: int, tenant_name: str, landing: dict) -> int:
    """Occupy every slot of every date in the landing week.

    Rows are inserted directly so the test does not depend on which weekday it
    runs: dates inside the automatic freeze window cannot be booked through the
    API, yet bookings made before they froze still sit there in real life.
    """
    count = 0
    for day in landing['days']:
        for slot in day['slots']:
            if slot['booking'] is not None:
                continue
            count += 1
            db.add(DeploymentBooking(
                booking_reference=f"FILL-{day['day']}-{slot['slot_number']}",
                tenant_id=tenant_id, tenant_name=tenant_name,
                deployment_date=date.fromisoformat(day['day']), slot_number=slot['slot_number'],
                technology='Databricks', requester_name='Other team', requester_email='o@example.com',
                verifier_name='V', verifier_email='v@example.com',
                git_repository='https://git.example.com/x', implementation_summary='',
                deployment_description='', justification='Load test', impacted_region='APAC',
            ))
    db.commit()
    return count


def test_tenant_lands_on_the_nearest_week_even_when_it_is_fully_booked(db, user, tenant):
    """A fully booked week is exactly when tenants most need to see the pressure.

    Jumping to the first week with a free slot skipped it and showed an empty
    board instead.
    """
    before = _landing(user)
    filled = _fill_week_directly(db, tenant, 'EPCAT', before)

    after = _landing(user)
    assert after['week_start'] == before['week_start']
    visible = sum(1 for d in after['days'] for s in d['slots'] if s['booking'] is not None)
    assert visible == filled > 0
    assert not any(s['bookable'] for d in after['days'] for s in d['slots'])
    # ...and the tenant is still pointed straight at the next free slot.
    assert after['next_available']['week_start'] > after['week_start']
    assert after['landing_message'].startswith('No free slot this week. Next available slot:')


def test_other_tenants_bookings_are_visible_on_the_landing_week(db, user, other_tenant):
    before = _landing(user)
    _fill_week_directly(db, other_tenant, 'Encounters', before)
    seen = [s['booking'] for d in _landing(user)['days'] for s in d['slots'] if s['booking']]
    me = user.get('/api/auth/me').json()
    # None of these belong to the signed-in tenant user, yet all are shown.
    assert seen and all(b['created_by_user_id'] != me['id'] for b in seen)
    assert {b['tenant_name'] for b in seen} == {'Encounters'}


def test_the_next_available_pointer_targets_the_earliest_free_slot(user):
    landing = _landing(user)
    target = landing['next_available']
    assert target is not None

    week = user.get(f"/api/schedule?week={target['week_start']}").json()
    day = next(d for d in week['days'] if d['day'] == target['deployment_date'])
    slot = next(s for s in day['slots'] if s['slot_number'] == target['slot_number'])
    assert slot['bookable'] is True

    # Nothing earlier is free, from the landing week up to the target.
    cursor = landing['week_start']
    while cursor <= target['week_start']:
        board = user.get(f"/api/schedule?week={cursor}").json()
        earlier = [
            (d['day'], s['slot_number']) for d in board['days'] for s in d['slots']
            if s['bookable'] and (d['day'], s['slot_number']) < (target['deployment_date'], target['slot_number'])
        ]
        assert earlier == [], earlier
        cursor = (date.fromisoformat(cursor) + timedelta(days=7)).isoformat()


def test_browsing_and_admin_views_keep_the_selected_week(admin, user):
    initial = user.get('/api/schedule').json()
    assert user.get(f"/api/schedule?week={initial['week_start']}").json()['week_start'] == initial['week_start']
    admin_view = admin.get('/api/schedule?first_available=true').json()
    assert admin_view['week_start'] == initial['week_start']
    assert admin_view['next_available'] is None


def test_no_availability_returns_clear_message(admin, user):
    # Disable every slot configuration through the DB, independent of capacity defaults.
    from app.database import SessionLocal
    from app.models import DeploymentSlotConfiguration
    from sqlalchemy import select
    with SessionLocal() as db:
        for slot in db.scalars(select(DeploymentSlotConfiguration)):
            slot.enabled = False
        db.commit()
    result = user.get('/api/schedule?first_available=true')
    assert result.status_code == 200
    assert 'No bookable slots' in result.json()['landing_message']
