from datetime import timedelta
from pathlib import Path
import pytest
from sqlalchemy import select, func
from app.models import BookingAudit, DeploymentBooking
from app.utils.files import storage_root
from conftest import create_booking, booking_payload, post_booking


def test_clone_needs_fresh_documents_and_preserves_source(admin, user, tenant, next_monday, db):
    source = create_booking(user, tenant, next_monday, 1)
    row = db.get(DeploymentBooking, source['id'])
    row.status = 'COMPLETED'
    row.change_number = 'OLD-CHANGE'
    db.commit()
    user.post(f"/api/bookings/{row.id}/comments", json={'body': 'Do not copy discussion'})
    payload = booking_payload(tenant, next_monday + timedelta(days=1), 1,
                              clone_source_id=source['id'], jira_number=None, jira_url=None)
    denied = post_booking(user, payload, omit_documents={'IMPLEMENTATION_PLAN'})
    assert denied.status_code == 422
    assert db.scalar(select(func.count()).select_from(DeploymentBooking)) == 1
    cloned = post_booking(user, payload)
    assert cloned.status_code == 201, cloned.text
    new = cloned.json()['booking']
    assert source['booking_reference'] == 'pds-001'
    assert new['booking_reference'] == 'pds-002'
    assert new['cloned_from_reference'] == source['booking_reference']
    assert new['status'] == 'BOOKED' and new['change_number'] is None
    assert new['work_started_at'] is None and new['assigned_users'] == []
    assert new['jira_number'] is None
    assert {a['id'] for a in new['attachments']}.isdisjoint({a['id'] for a in source['attachments']})
    assert user.get(f"/api/bookings/{new['id']}/comments").json() == []
    assert user.get(f"/api/bookings/{source['id']}").json()['status'] == 'COMPLETED'


def test_clone_access_and_rm_cloning_other_user(admin, user, other_user, anon, tenant, next_monday):
    source = create_booking(user, tenant, next_monday, 1)

    # Any signed-in user can clone any schedule. The clone is theirs...
    mine = post_booking(other_user, booking_payload(tenant, next_monday, 3, clone_source_id=source['id']))
    assert mine.status_code == 201, mine.text
    clone = mine.json()['booking']
    assert clone['created_by_user_id'] == other_user.get('/api/auth/me').json()['id']
    assert clone['cloned_from_reference'] == source['booking_reference']
    # ...but cloning grants no control over the source.
    assert other_user.put(f"/api/bookings/{source['id']}", json=booking_payload(tenant, next_monday, 1)).status_code == 403
    assert other_user.request('DELETE', f"/api/bookings/{source['id']}", json={}).status_code == 403
    assert post_booking(anon, booking_payload(tenant, next_monday, 4, clone_source_id=source['id'])).status_code == 401

    payload = booking_payload(tenant, next_monday, 2, clone_source_id=source['id'])
    cloned = post_booking(admin, payload)
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()['booking']['created_by_user_id'] == admin.get('/api/auth/me').json()['id']
    assert post_booking(user, {**payload, 'clone_source_id': 999999}).status_code == 404


def test_search_all_dates_is_scoped_and_escapes_wildcards(admin, user, other_user, anon, tenant, next_monday, db):
    b = create_booking(user, tenant, next_monday, 1)
    row = db.get(DeploymentBooking, b['id'])
    row.deployment_date = next_monday - timedelta(days=100)
    row.status = 'COMPLETED'
    db.commit()
    path = '/api/bookings/search'
    assert user.get(path, params={'q': b['booking_reference'].lower()}).json()[0]['id'] == b['id']
    assert admin.get(path, params={'q': b['booking_reference']}).json()[0]['id'] == b['id']
    # Every schedule is readable by any signed-in user, so search finds it too.
    assert other_user.get(path, params={'q': b['booking_reference']}).json()[0]['id'] == b['id']
    assert anon.get(path, params={'q': b['booking_reference']}).status_code == 401
    assert user.get(path, params={'q': '%%'}).json() == []
    assert user.get(path, params={'q': '  '}).status_code == 422
    assert user.get(path, params={'q': 'PDS', 'before_id': b['id']}).json() == []


def upload(client, bid, files, internal=False):
    return client.post(f'/api/bookings/{bid}/comments/upload', data={'body': 'Please review files', 'internal': str(internal).lower()},
                       files=[('files', (name, body, 'application/octet-stream')) for name, body in files])


def test_comment_files_download_privacy_and_document_separation(admin, user, other_user, anon, tenant, next_monday):
    b = create_booking(user, tenant, next_monday, 1)
    bid = b['id']
    public = upload(user, bid, [('../../report.txt', b'public evidence'), ('image.png', b'image bytes')])
    assert public.status_code == 201, public.text
    c = public.json()
    assert len(c['attachments']) == 2
    a = c['attachments'][0]
    assert a['original_filename'] == 'report.txt'
    url = f"/api/bookings/{bid}/comments/{c['id']}/attachments/{a['id']}"
    response = user.get(url)
    assert response.content == b'public evidence'
    assert 'attachment' in response.headers['content-disposition']
    assert response.headers['x-content-type-options'] == 'nosniff'
    # Public comment files are readable by any signed-in user.
    assert other_user.get(url).content == b'public evidence'
    assert anon.get(url).status_code == 401
    internal = upload(admin, bid, [('private.txt', b'private')], internal=True).json()
    private_url = f"/api/bookings/{bid}/comments/{internal['id']}/attachments/{internal['attachments'][0]['id']}"
    assert admin.get(private_url).content == b'private'
    # Internal RM files stay hidden from the owner and from every other tenant.
    for client in (user, other_user):
        assert client.get(private_url).status_code == 404
        assert 'private.txt' not in client.get(f'/api/bookings/{bid}/comments').text
        assert 'private.txt' not in client.get(f'/api/bookings/{bid}/audit').text
    assert upload(user, bid, [('private.txt', b'private')], internal=True).status_code == 403
    after = user.get(f'/api/bookings/{bid}').json()
    assert after['documents'] == b['documents'] and after['attachments'] == b['attachments']
    assert admin.get('/api/admin/audit').status_code == 200
    another = create_booking(user, tenant, next_monday, 2)
    assert admin.get(url.replace(f'/bookings/{bid}/', f"/bookings/{another['id']}/")).status_code == 404


def test_comment_files_size_boundary_and_atomic_failure(admin, user, tenant, next_monday, db):
    b = create_booking(user, tenant, next_monday, 1)
    exact = upload(user, b['id'], [('exact.txt', b'x' * (20 * 1024 * 1024))])
    assert exact.status_code == 201, exact.text
    before_files = {p for p in storage_root().rglob('*') if p.is_file()}
    before_count = db.scalar(select(func.count()).select_from(BookingAudit))
    denied = upload(user, b['id'], [('valid.txt', b'ok'), ('large.txt', b'x' * (20 * 1024 * 1024 + 1))])
    assert denied.status_code == 413, denied.text
    assert {p for p in storage_root().rglob('*') if p.is_file()} == before_files
    assert db.scalar(select(func.count()).select_from(BookingAudit)) == before_count
    for files in [[('bad.exe', b'x')], [('empty.txt', b'')], [('ok.txt', b'x')] * 11]:
        assert upload(user, b['id'], files).status_code == 422


def test_schedule_number_reserved_after_permanent_delete(admin, user, tenant, next_monday, db):
    from app.services.booking_service import delete_booking, Actor
    b = create_booking(user, tenant, next_monday, 1)
    delete_booking(db, db.get(DeploymentBooking, b['id']), Actor(is_admin=True, admin_username='testadmin'))
    new = create_booking(user, tenant, next_monday, 1)
    assert b['booking_reference'] == 'pds-001'
    assert new['booking_reference'] == 'pds-002'


def test_short_numbers_grow_beyond_three_digits_and_ignore_legacy_dates(user, tenant, next_monday, db):
    from app.services.booking_service import next_booking_reference
    booking = create_booking(user, tenant, next_monday, 1)
    row = db.get(DeploymentBooking, booking['id'])
    row.booking_reference = 'PDS-20261004-999'
    db.commit()
    assert next_booking_reference(db, next_monday) == 'pds-002'
    row.booking_reference = 'pds-999'
    db.commit()
    assert next_booking_reference(db, next_monday + timedelta(days=30)) == 'pds-1000'
    assert user.get('/api/bookings/search', params={'q':'PDS-999'}).json()[0]['id'] == row.id
