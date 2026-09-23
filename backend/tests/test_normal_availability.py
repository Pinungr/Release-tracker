"""Normal availability is role-independent; manual overrides are explicit."""
from datetime import date, timedelta

import pytest

from app.models import DeploymentBooking, DeploymentSlotConfiguration
from app.services import booking_service, presenters
from conftest import booking_payload, create_booking, post_booking


TODAY = date(2026, 9, 22)
SOURCE = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(booking_service, "today_local", lambda: TODAY)
    monkeypatch.setattr(presenters, "today_local", lambda: TODAY)


@pytest.mark.parametrize("as_admin", [False, True])
def test_normal_options_and_board_exclude_every_closed_slot(admin, user, tenant, db, as_admin):
    booking = create_booking(user, tenant, SOURCE, 1)
    holiday = date(2026, 9, 27)
    assert admin.post("/api/admin/holidays", json={
        "holiday_date": str(holiday), "name": "Holiday", "is_full_day": True,
    }).status_code == 201
    # Sep 23/24 are protected; Sep 25/26 are Friday/Saturday; Sep 27 is a holiday.
    first = date(2026, 9, 28)
    assert admin.post("/api/admin/slot-freezes", json={
        "freeze_date": str(first), "slot_number": 1,
    }).status_code == 200
    cfg = db.query(DeploymentSlotConfiguration).filter_by(slot_number=2).one()
    cfg.enabled = False
    db.commit()
    assert admin.post(f"/api/admin/day-capacity/{first}/remove-slot").status_code == 200
    create_booking(admin, tenant, first, 3)
    client = admin if as_admin else user
    options = client.get(f"/api/bookings/{booking['id']}/reschedule-options?limit=100").json()
    keys = [(date.fromisoformat(o['deployment_date']), o['slot_number']) for o in options]
    assert keys and keys == sorted(keys)
    assert keys[0] == (first + timedelta(days=1), 1)
    assert all(day > TODAY and day.weekday() not in (4, 5) for day, _ in keys)
    assert all(day not in {holiday, date(2026, 9, 23), date(2026, 9, 24), first} for day, _ in keys)
    assert all(slot != 2 for _, slot in keys)
    board = client.get(f"/api/schedule?week={first}").json()
    day = next(d for d in board['days'] if d['day'] == str(first))
    assert not any(s['bookable'] for s in day['slots'])
    assert not any(slot['bookable'] for slot in day['slots'])
    assert day['regular_slots_total'] == day['regular_slots_used'] == 1
    assert board['summary']['regular_slots_available'] == sum(
        s['bookable'] for d in board['days'] for s in d['slots']
    )


@pytest.mark.parametrize("as_admin", [False, True])
@pytest.mark.parametrize("restriction", [
    "friday", "saturday", "holiday", "current", "past", "protected",
    "disabled", "capacity", "missing", "frozen", "occupied",
])
def test_direct_reschedule_rejects_invalid_target(admin, user, tenant, db, as_admin, restriction):
    booking = create_booking(user, tenant, SOURCE, 1)
    target, slot = date(2026, 10, 5), 1
    if restriction in {"friday", "saturday", "current", "past", "protected"}:
        target = {"friday": date(2026, 9, 25), "saturday": date(2026, 9, 26),
                  "current": TODAY, "past": TODAY - timedelta(days=1),
                  "protected": TODAY + timedelta(days=1)}[restriction]
    elif restriction == "holiday":
        admin.post("/api/admin/holidays", json={"holiday_date": str(target), "name": "Closed", "is_full_day": True})
    elif restriction == "disabled":
        db.query(DeploymentSlotConfiguration).filter_by(slot_number=1).one().enabled = False
        db.commit()
    elif restriction == "capacity":
        assert admin.post(f"/api/admin/day-capacity/{target}/remove-slot").status_code == 200
        slot = 4
    elif restriction == "missing":
        slot = 50
    elif restriction == "frozen":
        admin.post("/api/admin/slot-freezes", json={"freeze_date": str(target), "slot_number": slot})
    elif restriction == "occupied":
        create_booking(admin, tenant, target, slot)
    client = admin if as_admin else user
    before_audit = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    response = client.post(f"/api/bookings/{booking['id']}/reschedule", json={
        "deployment_date": str(target), "slot_number": slot, "override_reason": "Must not bypass normal rules",
    })
    assert response.status_code in (400, 404, 409, 423), response.text
    detail = client.get(f"/api/bookings/{booking['id']}").json()
    assert detail['deployment_date'] == str(SOURCE) and detail['slot_number'] == 1
    assert admin.get(f"/api/admin/audit?booking_id={booking['id']}").json() == before_audit


@pytest.mark.parametrize("reason,target", [
    ("CURRENT_DATE", TODAY), ("PAST_DATE", TODAY - timedelta(days=1)),
    ("AUTOMATIC_DATE_FREEZE", TODAY + timedelta(days=1)),
])
def test_all_booking_modifications_respect_date_protection(admin, user, other_user, tenant, db, reason, target):
    from conftest import promote_to_release_manager

    booking = create_booking(user, tenant, SOURCE, 1)
    rm_id = promote_to_release_manager(admin, other_user)
    assert admin.post(f"/api/admin/bookings/{booking['id']}/assign-users", json={"user_ids": [rm_id]}).status_code == 200
    row = db.get(DeploymentBooking, booking['id'])
    row.deployment_date = target
    db.commit()
    path = f"/api/bookings/{booking['id']}"
    for client in (admin, user):
        detail = client.get(path).json()
        assert detail['lock_reason'] == reason
        for flag in ('can_edit', 'can_cancel', 'can_reschedule', 'can_assign_rm', 'can_start_work', 'can_manage_attachments'):
            assert not detail[flag], flag
        assert client.put(path, json=booking_payload(tenant, target, 1)).status_code == 423
        assert client.request('DELETE', path, json={}).status_code == 423
        assert client.post(path + '/reschedule', json={'deployment_date': str(SOURCE), 'slot_number': 2}).status_code == 423
        assert client.get(path + '/reschedule-options').json() == []
        assert client.post(path + '/attachments', data={'category': 'SUPPORTING_DOCUMENTS'}, files={'file': ('note.txt', b'note')}).status_code == 423
        assert client.delete(path + f"/attachments/{booking['attachments'][0]['id']}").status_code == 423
    for suffix, payload in [('assign-users', {'user_ids': [rm_id]}), ('status', {'status': 'COMPLETED'})]:
        assert admin.post(f"/api/admin/bookings/{booking['id']}/{suffix}", json=payload).status_code == 423
    for client in (admin, other_user):
        assert client.post(path + '/start-work', json={'change_number': 'CHG12345'}).status_code == 423
    rm_detail = other_user.get(path).json()
    assert rm_detail['can_download_attachments'] and not rm_detail['can_manage_attachments']
    attachment_path = path + f"/attachments/{booking['attachments'][0]['id']}"
    assert other_user.get(attachment_path + '/download').status_code == 200
    assert other_user.delete(attachment_path).status_code == 423


def test_explicit_override_is_separate_and_audited(admin, user, tenant):
    saturday = date(2026, 10, 10)
    payload = booking_payload(tenant, saturday, 1)
    assert post_booking(admin, payload).status_code == 400
    payload['manual_override'] = True
    assert post_booking(admin, payload).status_code == 403
    payload['override_reason'] = 'Exceptional approved deployment'
    assert post_booking(user, payload).status_code == 403
    result = post_booking(admin, payload)
    assert result.status_code == 201, result.text
    booking = result.json()['booking']
    audit = admin.get(f"/api/admin/audit?booking_id={booking['id']}").json()
    assert any(e['override_reason'] == payload['override_reason'] for e in audit)
    board = admin.get(f'/api/schedule?week={saturday}').json()
    assert not any(d['weekday'] in ('Friday', 'Saturday') for d in board['days'])
    assert admin.get(f"/api/bookings/{booking['id']}").status_code == 200


def test_default_jira_and_overnight_timing(admin, user, tenant):
    booking = create_booking(user, tenant, SOURCE, 1, jira_number=None, jira_url=None)
    assert booking['jira_number'] is None and booking['change_number'] is None
    assert '09:00 PM' in booking['slot_time'] and '05:00 AM' in booking['slot_time']
    assert not admin.get('/api/admin/settings').json()['jira_required_at_booking']


def test_missing_configuration_does_not_shift_date_capacity(admin, user, tenant, db):
    booking = create_booking(user, tenant, SOURCE, 1)
    first = date(2026, 9, 27)
    admin.post(f'/api/admin/day-capacity/{first}/remove-slot')
    db.delete(db.query(DeploymentSlotConfiguration).filter_by(slot_number=2).one())
    db.commit()
    options = admin.get(f"/api/bookings/{booking['id']}/reschedule-options?limit=100").json()
    assert not any(o['slot_number'] == 2 for o in options)
    assert [o['slot_number'] for o in options if o['deployment_date'] == str(first)] == [1, 3]




def test_emergency_records_also_respect_protected_dates(admin, tenant, db):
    from conftest import emergency_payload
    protected = TODAY + timedelta(days=1)
    assert post_booking(admin, emergency_payload(tenant, protected)).status_code == 423
    response = post_booking(admin, emergency_payload(tenant, SOURCE))
    assert response.status_code == 201
    booking = response.json()['booking']
    assert admin.post(f"/api/admin/bookings/{booking['id']}/move", json={
        'deployment_date': str(protected), 'slot_number': None,
    }).status_code == 423
    db.get(DeploymentBooking, booking['id']).deployment_date = protected
    db.commit()
    assert not admin.get(f"/api/bookings/{booking['id']}").json()['can_edit']
    assert admin.post(f"/api/bookings/{booking['id']}/start-work", json={'change_number': 'CHG123'}).status_code == 423


def test_release_manager_must_be_assigned_before_starting_work(admin, user, other_user, tenant):
    from conftest import promote_to_release_manager

    booking = create_booking(user, tenant, SOURCE, 1)
    path = f"/api/bookings/{booking['id']}"
    rm_id = promote_to_release_manager(admin, other_user)

    # A Release Manager has release/admin access, but cannot start this CRQ
    # until explicitly assigned.
    detail = other_user.get(path)
    assert detail.status_code == 200
    assert detail.json()['can_start_work'] is False
    assert other_user.post(path + '/start-work', json={'change_number': 'CHG-RM-001'}).status_code == 403

    assigned = admin.post(
        f"/api/admin/bookings/{booking['id']}/assign-users",
        json={'user_ids': [rm_id]},
    )
    assert assigned.status_code == 200
    assert other_user.get(path).json()['can_start_work'] is True
    assert other_user.post(path + '/start-work', json={'change_number': 'CHG-RM-001'}).status_code == 200
