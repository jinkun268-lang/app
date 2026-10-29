import pytest
from fastapi.testclient import TestClient
from server.app.main import create_app
from server.app.common import new_uuid7
from test_uploads import BASE, login, bearer

@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
def test_batch_question_persistence_and_permissions(backend, tmp_path):
    url = 'memory' if backend == 'memory' else f'sqlite:///{tmp_path}/meta.db'
    app = create_app(url)
    with TestClient(app) as c:
        owner = bearer(login(c, 'collector1'))
        other = bearer(login(c, 'collector2'))
        expert = bearer(login(c, 'expert'))
        bid, qid = new_uuid7(), new_uuid7()
        body = dict(name='外业', place='果园', collector='张三', default_cultivar_id='huyou', note='', closed=False)
        r = c.put(f'{BASE}/batches/{bid}', json=body, headers=owner)
        assert r.status_code == 200, r.text
        assert c.put(f'{BASE}/batches/{bid}', json=body, headers=other).status_code == 404
        assert c.get(f'{BASE}/batches', headers=other).json()['total'] == 0
        assert c.get(f'{BASE}/batches?page=1&page_size=1', headers=expert).json()['total'] == 1
        q = dict(question_id=qid, text='叶片需要补拍吗？')
        assert c.post(f'{BASE}/questions', json=q, headers=owner).status_code == 201
        assert c.post(f'{BASE}/questions', json=q, headers=owner).status_code == 200
        assert c.post(f'{BASE}/questions', json={**q, 'text':'不同内容'}, headers=owner).status_code == 409
        assert c.get(f'{BASE}/questions/{qid}', headers=other).status_code == 404
        assert c.patch(f'{BASE}/questions/{qid}/answer', json={'answer':'请补拍清晰叶背'}, headers=owner).status_code == 403
        assert c.patch(f'{BASE}/questions/{qid}/answer', json={'answer':'请补拍清晰叶背'}, headers=expert).status_code == 200
        assert c.get(f'{BASE}/questions/{qid}', headers=owner).json()['answer'] == '请补拍清晰叶背'
        assert c.get(f'{BASE}/questions?page=2&page_size=1', headers=owner).json()['items'] == []
    if backend != 'memory':
        with TestClient(create_app(url)) as c:
            owner = bearer(login(c, 'collector1'))
            assert c.get(f'{BASE}/questions/{qid}', headers=owner).json()['status'] == 'answered'
            assert c.get(f'{BASE}/batches', headers=owner).json()['total'] == 1

@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
def test_batch_upload_metadata_attachment_and_closed_rules(backend, tmp_path):
    from test_uploads import png_bytes, image_decl, declaration, put_image
    app = create_app('memory' if backend == 'memory' else f'sqlite:///{tmp_path}/data.db')
    with TestClient(app) as c:
        token = login(c, 'collector1'); owner = bearer(token)
        other = bearer(login(c, 'collector2'))
        bid = new_uuid7()
        batch = dict(name='批次一',place='果园A',collector='甲',closed=False)
        assert c.put(f'{BASE}/batches/{bid}', json=batch, headers=owner).status_code == 200
        data = png_bytes(8,6); image = image_decl(new_uuid7(), data,'image/png',8,6)
        decl = {**declaration(new_uuid7(), image), 'batch_id': bid, 'latitude':30.1, 'longitude':120.2,'location_accuracy_m':12}
        assert c.post(f'{BASE}/uploads',json=decl,headers=other).status_code == 404
        r = c.post(f'{BASE}/uploads',json=decl,headers=owner)
        assert r.status_code == 201, r.text
        uid = r.json()['upload_id']
        assert put_image(c,token,uid,image,data).status_code == 201
        assert c.post(f'{BASE}/uploads/{uid}/complete',headers=owner).status_code == 200
        sid = decl['sample_id']
        detail = c.get(f'{BASE}/samples/{sid}',headers=owner).json()
        assert detail['latitude'] == 30.1
        assert detail['batch_snapshot']['place'] == '果园A'
        assert c.get(f'{BASE}/samples?batch_id={bid}',headers=owner).json()['total'] == 1
        assert c.get(f'{BASE}/samples?batch_id={new_uuid7()}',headers=owner).json()['total'] == 0
        qid = new_uuid7()
        q = {'question_id':qid, 'text':'怎么拍？', 'sample_id':sid}
        assert c.post(f'{BASE}/questions',json=q,headers=other).status_code == 404
        r = c.post(f'{BASE}/questions',json=q,headers=owner)
        assert r.status_code == 201
        assert r.json()['images'][0]['image_id'] == image['image_id']
        assert r.json()['sample']['sample_id'] == sid
        assert c.put(f'{BASE}/batches/{bid}',json={**batch,'closed':True},headers=owner).status_code == 200
        # Existing declarations remain resumable after batch closure.
        assert c.post(f'{BASE}/uploads',json=decl,headers=owner).status_code == 200
        # Closing an offline batch stops new capture in the client, but must not
        # strand photos already on the phone that have never been declared.
        offline_image = image_decl(new_uuid7(), data, 'image/png', 8, 6)
        offline_decl = {**declaration(new_uuid7(), offline_image), 'batch_id': bid}
        offline = c.post(f'{BASE}/uploads', json=offline_decl, headers=owner)
        assert offline.status_code == 201, offline.text
        assert put_image(c, token, offline.json()['upload_id'], offline_image, data).status_code == 201
        assert c.post(f"{BASE}/uploads/{offline.json()['upload_id']}/complete", headers=owner).status_code == 200
        invalid = {**decl, 'sample_id':new_uuid7(), 'latitude':95}
        assert c.post(f'{BASE}/uploads',json=invalid,headers=owner).status_code == 422
        # Training export retains the batch/location snapshot after batch edits.
        import csv, io, zipfile
        from test_flow import wait_export
        expert = bearer(login(c,'expert')); admin = login(c,'admin')
        assert c.patch(f'{BASE}/samples/{sid}/review',json={'expected_version':0,'review_status':'confirmed'},headers=expert).status_code == 200
        assert c.patch(f"{BASE}/samples/{sid}/images/{image['image_id']}/quality",json={'expected_version':0,'quality_status':'usable'},headers=bearer(admin)).status_code == 200
        # declaration's default class is unknown: use eligible citrus_canker before export.
        assert c.patch(f'{BASE}/samples/{sid}/review',json={'expected_version':1,'review_status':'corrected','final_cultivar_id':'huyou','final_part':'leaf','final_class_id':'citrus_canker'},headers=expert).status_code == 200
        job = c.post(f'{BASE}/exports',json={'format':'dataset'},headers={**bearer(admin),'Idempotency-Key':new_uuid7()}).json()
        assert job['item_count'] == 1
        assert c.put(f'{BASE}/batches/{bid}',json={**batch,'place':'改后地点','closed':True},headers=owner).status_code == 200
        assert wait_export(c,admin,job['export_id'])['status'] == 'succeeded'
        archive = zipfile.ZipFile(io.BytesIO(c.get(f"{BASE}/exports/{job['export_id']}/download",headers=bearer(admin)).content))
        row = list(csv.DictReader(io.StringIO(archive.read('collection.csv').decode('utf-8-sig'))))[0]
        assert row['place'] == '果园A' and row['latitude'] == '30.1' and row['batch_id'] == bid


def test_sqlite_v2_nullable_upgrade_preserves_existing_samples(tmp_path):
    import sqlite3
    from test_flow import upload_two_images
    url = f'sqlite:///{tmp_path}/old.db'
    with TestClient(create_app(url)) as c:
        info = upload_two_images(c)
        sid = info['sample_id']
        before = c.get(f'{BASE}/samples/{sid}',headers=bearer(info['owner'])).json()
    with sqlite3.connect(tmp_path / 'old.db') as db:
        for column in ('batch_id','batch_snapshot','latitude','longitude','location_accuracy_m'):
            db.execute(f'ALTER TABLE samples DROP COLUMN {column}')
        db.execute('ALTER TABLE export_items DROP COLUMN collection_metadata')
        db.execute('DROP TABLE questions')
        db.execute('DROP TABLE batches')
        db.execute("UPDATE meta_schema SET value='2' WHERE name='schema_version'")
    # Repeat startup to cover additive migration idempotence.
    for _ in range(2):
        with TestClient(create_app(url)) as c:
            token = login(c,'collector1')
            detail = c.get(f'{BASE}/samples/{sid}', headers=bearer(token)).json()
            assert detail == before
            assert detail['batch_id'] is None and detail['latitude'] is None
