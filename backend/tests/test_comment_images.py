import base64
import json
from sqlalchemy import func, select
from app.models import BookingAudit, BookingAttachment
from conftest import create_booking

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def upload_image(client, bid, internal=False, content=PNG):
    r = client.post(f'/api/bookings/{bid}/comments/upload', data={'body':'Screenshot', 'internal':str(internal).lower()}, files=[('files',('screen.png',content,'image/png'))])
    assert r.status_code == 201, r.text
    c = r.json()
    return {'kind':'comment','comment_id':c['id'],'attachment_id':c['attachments'][0]['id']}


def test_reuse_images_and_emoji_without_duplicating_files(admin, user, tenant, next_monday, db):
    b = create_booking(user, tenant, next_monday, 1)
    bid = b['id']
    ref = upload_image(user, bid)
    original_attachments = db.scalar(select(func.count()).select_from(BookingAttachment))
    picker = user.get(f'/api/bookings/{bid}/comment-images').json()
    assert any(i['attachment_id'] == ref['attachment_id'] for i in picker['images'])
    result = user.post(f'/api/bookings/{bid}/comments', json={'body':'Verified ✅ 👍', 'image_refs':[ref, ref]})
    assert result.status_code == 201, result.text
    assert result.json()['body'] == 'Verified ✅ 👍'
    assert len(result.json()['images']) == 1
    assert result.json()['attachments'] == []
    assert db.scalar(select(func.count()).select_from(BookingAttachment)) == original_attachments
    preview = user.get(f'/api/bookings/{bid}/comment-images/preview', params=ref)
    assert preview.status_code == 200
    assert preview.content == PNG
    assert preview.headers['content-type'] == 'image/png'
    assert preview.headers['cache-control'] == 'private, no-store'


def test_internal_images_cannot_leak_into_public_comments(admin, user, other_user, anon, tenant, next_monday):
    b = create_booking(user, tenant, next_monday, 1)
    bid = b['id']
    ref = upload_image(admin, bid, internal=True)
    path = f'/api/bookings/{bid}'
    assert user.get(path+'/comment-images').json()['images'] == []
    assert admin.get(path+'/comment-images').json()['images'] == []
    assert admin.get(path+'/comment-images?internal=true').json()['images'][0]['internal'] is True
    assert user.get(path+'/comment-images?internal=true').status_code == 403
    for client in (user, admin):
        denied = client.post(path+'/comments', json={'body':'Public reference', 'image_refs':[ref]})
        assert denied.status_code == 403
    assert user.get(path+'/comment-images/preview', params=ref).status_code == 403
    assert admin.get(path+'/comment-images/preview', params=ref).status_code == 200
    assert admin.post(path+'/comments', json={'body':'Private reference', 'internal':True, 'image_refs':[ref]}).status_code == 201
    # A non-owner tenant may use the picker, but gets exactly what the owner
    # gets: no internal images, and no preview of one.
    assert other_user.get(path+'/comment-images').json()['images'] == []
    assert other_user.get(path+'/comment-images?internal=true').status_code == 403
    assert other_user.get(path+'/comment-images/preview', params=ref).status_code == 403
    assert anon.get(path+'/comment-images').status_code == 401
    assert anon.get(path+'/comment-images/preview', params=ref).status_code == 401
    denied_upload = admin.post(path+'/comments/upload', data={'body':'No bypass', 'image_refs':json.dumps([ref])}, files=[('files',('fresh.png',PNG,'image/png'))])
    assert denied_upload.status_code == 403


def test_document_image_refs_and_cross_schedule_rejection(admin, user, tenant, next_monday):
    b = create_booking(user, tenant, next_monday, 1)
    path = f"/api/bookings/{b['id']}"
    uploaded = user.post(path+'/attachments', data={'category':'SUPPORTING_DOCUMENTS'}, files={'file':('evidence.png',PNG,'image/png')})
    assert uploaded.status_code == 200
    image = next(a for a in uploaded.json()['attachments'] if a['original_filename'] == 'evidence.png')
    ref = {'kind':'document','attachment_id':str(image['id'])}
    assert any(i['attachment_id'] == ref['attachment_id'] for i in user.get(path+'/comment-images').json()['images'])
    assert user.post(path+'/comments', json={'body':'See evidence', 'image_refs':[ref]}).status_code == 201
    new = create_booking(user, tenant, next_monday, 2)
    assert admin.post(f"/api/bookings/{new['id']}/comments", json={'body':'Wrong schedule', 'image_refs':[ref]}).status_code == 404
    assert admin.get(f"/api/bookings/{new['id']}/comment-images/preview", params=ref).status_code == 404
    user.delete(path+f"/attachments/{image['id']}")
    assert user.get(path+'/comment-images/preview', params=ref).status_code == 404
    assert user.post(path+'/comments', json={'body':'Deleted', 'image_refs':[ref]}).status_code == 404


def test_preview_rejects_fake_image_and_too_many_refs(admin, user, tenant, next_monday):
    b = create_booking(user, tenant, next_monday, 1)
    ref = upload_image(user, b['id'], content=b'<html><script>unsafe</script></html>')
    path = f"/api/bookings/{b['id']}"
    assert user.get(path+'/comment-images/preview', params=ref).status_code == 415
    assert user.post(path+'/comments', json={'body':'Too many', 'image_refs':[ref]*11}).status_code == 422
    assert user.post(path+'/comments/upload', data={'body':'Bad json','image_refs':'invalid'}, files=[('files',('ok.txt',b'ok','text/plain'))]).status_code == 422


def test_picker_paginates_old_images(admin, user, tenant, next_monday, db):
    b = create_booking(user, tenant, next_monday, 1)
    ref = upload_image(user, b['id'])
    for _ in range(50):
        db.add(BookingAudit(booking_id=b['id'],booking_reference=b['booking_reference'],event_type='COMMENT_ADDED',actor_type='USER',new_values=json.dumps({'body':'Later','author_id':1,'author_name':'User'})))
    db.commit()
    path=f"/api/bookings/{b['id']}/comment-images"
    page=user.get(path).json()
    assert page['next_before_id'] and page['images'] == []
    older=user.get(path,params={'before_id':page['next_before_id']}).json()
    assert older['images'][0]['attachment_id'] == ref['attachment_id']
