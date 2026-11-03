"""Real upload → batch browsing → multiselect/manual frozen export, on memory and SQL."""
import csv
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from server.app.common import new_uuid7
from server.app.main import create_app
from test_flow import wait_export
from test_uploads import BASE, bearer, check_schema, declaration, declare, image_decl, login, png_bytes, put_image


@pytest.fixture(params=['memory', 'sqlite'])
def setup(request, tmp_path):
    database = 'memory' if request.param == 'memory' else f'sqlite:///{tmp_path}/metadata.db'
    app = create_app(database)
    with TestClient(app) as client:
        owner, expert, admin = login(client, 'collector1'), login(client, 'expert'), login(client, 'admin')
        batches = [new_uuid7(), new_uuid7()]
        for index, bid in enumerate(batches):
            # First batch was created just after Beijing midnight, before UTC midnight.
            batch = dict(name=f'采集{index}', created_at=f'2026-10-{21 + index}T16:30:00Z', closed=False)
            assert client.put(f'{BASE}/batches/{bid}', json=batch, headers=bearer(owner)).status_code == 200
        records = []
        for index in range(4):
            data = png_bytes(color=(10 + index, 50, 80))
            image = image_decl(new_uuid7(), data, 'image/png', 8, 6)
            sid = new_uuid7()
            body = {**declaration(sid, image), 'batch_id': batches[0 if index < 3 else 1]}
            created = declare(client, owner, body)
            uid = created['upload_id']
            assert put_image(client, owner, uid, image, data).status_code == 201
            assert client.post(f'{BASE}/uploads/{uid}/complete', headers=bearer(owner)).status_code == 200
            if index in (0, 1, 3):
                payload = dict(expected_version=0, review_status='corrected', final_class_id='citrus_canker', final_part='leaf', final_cultivar_id='huyou' if index != 1 else 'xiangyou')
                assert client.patch(f'{BASE}/samples/{sid}/review', json=payload, headers=bearer(expert)).status_code == 200
            if index in (0, 3):
                assert client.patch(f"{BASE}/samples/{sid}/images/{image['image_id']}/quality", json=dict(expected_version=0, quality_status='usable'), headers=bearer(admin)).status_code == 200
            records.append((sid, image['image_id']))
        yield client, admin, owner, expert, batches, records


def create(client, admin, payload, key=None):
    response = client.post(f'{BASE}/exports', json={'format': 'dataset', **payload}, headers={**bearer(admin), 'Idempotency-Key': key or new_uuid7()})
    if response.status_code == 202:
        wait_export(client, admin, response.json()['export_id'])
    return response


def test_batch_browser_scopes_quality_and_roles(setup):
    client, admin, owner, expert, batches, records = setup
    for token in (owner, expert):
        assert client.get(f'{BASE}/training/batches', headers=bearer(token)).status_code == 403
        assert client.get(f'{BASE}/training/batches/{batches[0]}/images', headers=bearer(token)).status_code == 403
    response = client.get(f'{BASE}/training/batches?page_size=1', headers=bearer(admin)).json()
    check_schema('TrainingBatchPage', response)
    assert response['total'] == 2 and len(response['items']) == 1
    rows = client.get(f'{BASE}/training/batches', headers=bearer(admin)).json()['items']
    batch = next(row for row in rows if row['batch_id'] == batches[0])
    assert (batch['image_count'], batch['reviewed_count'], batch['pending_count'], batch['usable_count']) == (3, 2, 1, 1)
    response = client.get(f'{BASE}/training/batches/{batches[0]}/images?reviewed_only=true', headers=bearer(admin)).json()
    check_schema('TrainingImagePage', response)
    assert {image['image_id'] for image in response['items']} == {records[0][1], records[1][1]}
    assert all('file_key' not in image and 'sha256' not in image for image in response['items'])
    assert client.get(f'{BASE}/training/batches/{batches[0]}/images?page=2&page_size=2', headers=bearer(admin)).json()['total'] == 3


def test_multiselect_intersection_and_defaults(setup):
    client, admin, _, _, batches, records = setup
    scope = dict(batch_ids=batches, class_ids=['citrus_canker', 'unknown'], cultivar_ids=['huyou', 'xiangyou'])
    assert create(client, admin, scope).json()['item_count'] == 2
    assert create(client, admin, {**scope, 'review_status': 'reviewed', 'quality_status': 'all'}).json()['item_count'] == 3
    assert create(client, admin, {**scope, 'review_status': 'reviewed', 'quality_status': 'pending'}).json()['item_count'] == 1
    assert create(client, admin, {**scope, 'cultivar_ids': ['xiangyou'], 'quality_status': 'all'}).json()['item_count'] == 1
    # "unknown" plus a second class is a union; the cultivar condition remains an intersection.
    result = create(client, admin, {**scope, 'review_status': 'unreviewed', 'cultivar_ids': ['unknown', 'huyou']})
    assert result.status_code == 202, result.text
    assert result.json()['item_count'] == 1
    assert result.json()['filters']['quality_status'] == 'all'


def test_manual_selection_hard_scope_and_creation_dates(setup):
    client, admin, _, _, batches, records = setup
    payload = dict(batch_ids=[batches[0]], image_ids=[records[1][1], records[2][1]], class_ids=['citrus_canker', 'unknown'])
    # Explicit images override defaults, including pending quality and unreviewed images in an open batch.
    response = create(client, admin, {**payload, 'batch_created_from': '2026-10-22', 'batch_created_to': '2026-10-22'})
    assert response.status_code == 202, response.text
    assert response.json()['item_count'] == 2
    assert create(client, admin, {**payload, 'image_ids': [records[3][1]]}).status_code == 409
    assert create(client, admin, {**payload, 'class_ids': ['citrus_canker']}).status_code == 409
    assert create(client, admin, {**payload, 'cultivar_ids': ['huyou']}).status_code == 409
    assert create(client, admin, {**payload, 'batch_created_to': '2026-10-21'}).status_code == 409
    assert create(client, admin, {**payload, 'batch_created_from': '2026-10-23', 'batch_created_to': '2026-10-22'}).status_code == 422
    assert create(client, admin, {**payload, 'image_ids': []}).status_code == 422


def test_zip_freezes_exact_ids_labels_statuses_and_batch_snapshot(setup):
    client, admin, owner, expert, batches, records = setup
    payload = dict(name='多选训练集', batch_ids=[batches[0]], image_ids=[records[0][1], records[2][1]], class_ids=['citrus_canker', 'unknown'], cultivar_ids=['huyou', 'unknown'])
    key = new_uuid7()
    response = create(client, admin, payload, key)
    assert response.status_code == 202, response.text
    job = response.json()
    check_schema('ExportJob', job)
    assert create(client, admin, payload, key).json()['export_id'] == job['export_id']
    assert create(client, admin, {**payload, 'image_ids': [records[0][1]]}, key).status_code == 409
    assert client.put(f'{BASE}/batches/{batches[0]}', json=dict(name='新批次名', closed=True), headers=bearer(owner)).status_code == 200
    assert client.patch(f'{BASE}/samples/{records[2][0]}/review', json=dict(expected_version=0, review_status='corrected', final_class_id='citrus_canker', final_cultivar_id='xiangyou', final_part='leaf'), headers=bearer(expert)).status_code == 200
    assert wait_export(client, admin, job['export_id'])['status'] == 'succeeded'
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{BASE}/exports/{job['export_id']}/download", headers=bearer(admin)).content))
    labels = list(csv.DictReader(io.StringIO(archive.read('labels.csv').decode())))
    assert {row['image_id'] for row in labels} == {records[0][1], records[2][1]}
    unreviewed = next(row for row in labels if row['image_id'] == records[2][1])
    assert (unreviewed['review_status'], unreviewed['quality_status'], unreviewed['label_source'], unreviewed['class_id']) == ('unreviewed', 'not_assessed', 'collector_reported', 'unknown')
    collection = list(csv.DictReader(io.StringIO(archive.read('collection.csv').decode())))
    assert {row['batch_name'] for row in collection} == {'采集0'}
    assert job['filters']['batch_snapshots'][0]['name'] == '采集0'
    assert set(archive.namelist()) == {f'images/{records[0][1]}.png', f'images/{records[2][1]}.png', 'labels.csv', 'collection.csv', 'classes.csv'}


def test_excluded_and_unresolved_are_not_silently_selected(setup):
    client, admin, _, expert, batches, records = setup
    unresolved = client.patch(f'{BASE}/samples/{records[2][0]}/review', json=dict(expected_version=0, review_status='unresolved'), headers=bearer(expert))
    assert unresolved.status_code == 200, unresolved.text
    assert create(client, admin, dict(batch_ids=[batches[0]], review_status='unreviewed')).status_code == 422
    # An explicit "all" can still export unresolved collector labels with their actual status.
    assert create(client, admin, dict(batch_ids=[batches[0]], review_status='all', quality_status='all')).json()['item_count'] == 3
    excluded = client.post(f'{BASE}/samples/{records[0][0]}/exclude', json=dict(expected_version=1, reason='不进入训练集'), headers=bearer(admin))
    assert excluded.status_code == 200, excluded.text
    assert create(client, admin, dict(batch_ids=[batches[0]], image_ids=[records[0][1]])).status_code == 409
    response = client.get(f'{BASE}/training/batches/{batches[0]}/images', headers=bearer(admin)).json()
    assert records[0][1] not in {image['image_id'] for image in response['items']}
