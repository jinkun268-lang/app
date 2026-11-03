import hashlib
import io
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server.app.common import new_uuid7
from server.app.main import create_app
from server.tests.test_recognition import Classifier, png, token

BASE = '/api/v1/offline-recognitions'


class NamedClassifier(Classifier):
    test_name = '溃疡病'

    def predict(self, data):
        result = super().predict(data)
        result['candidates'][0].update(name=self.test_name, class_id='citrus_canker' if self.test_name == '溃疡病' else None)
        return result


def create_record(client, auth, name='溃疡病'):
    rid = new_uuid7()
    data = png()
    metadata = dict(crop_id='huyou', part='leaf', tree_age='adult', symptom='现场描述',
                    captured_at='2026-11-03T08:00:00+08:00', mime_type='image/png', file_size=len(data), sha256=hashlib.sha256(data).hexdigest())
    assert client.put('/api/v1/diagnoses/' + rid, headers=auth, json=metadata).status_code == 200
    client.app.state.recognizer.test_name = name
    result = client.post('/api/v1/diagnoses', params={'crop_id':'huyou','part':'leaf','tree_age':'adult'},
        headers={**auth,'Content-Type':'image/png','X-Image-ID':rid}, content=data)
    assert result.status_code == 200, result.text
    return client.get(BASE + '/' + rid, headers=auth).json()


@pytest.fixture(params=['memory', 'sqlite'])
def client(request, tmp_path):
    url = 'memory' if request.param == 'memory' else f'sqlite+pysqlite:///{tmp_path / "db.sqlite3"}'
    with TestClient(create_app(url, recognizer=NamedClassifier(), storage_root=tmp_path)) as value:
        yield value


def test_server_owned_records_media_permissions_and_no_client_result_upload(client):
    auth, other, expert, admin = (token(client, name) for name in ('collector1','collector2','expert','admin'))
    record = create_record(client, auth)
    path = BASE + '/' + record['record_id']
    assert record['source'] == 'server' and record['inference_status'] == 'succeeded'
    assert client.get(path).status_code == 401
    assert client.get(BASE, headers=admin).status_code == 403
    assert client.get(path, headers=other).status_code == 404
    assert client.get(path + '/image', headers=other).status_code == 404
    assert client.get(path + '/image', headers=expert).content == png()
    preview = client.get(path + '/image?preview=true', headers=expert)
    assert preview.headers['content-type'] == 'image/jpeg'
    assert 'no-store' in preview.headers['cache-control']
    assert client.put(path, headers=auth, json={'recognition':record['recognition']}).status_code == 405
    assert client.put(path + '/image', headers={**auth,'Content-Type':'image/png'}, content=png()).status_code == 405
    assert client.get('/api/v1/samples', headers=auth).json()['total'] == 0
    assert client.get(BASE, headers=other).json()['total'] == 0


def test_correction_is_optional_versioned_immutable_and_filters_current_result(client):
    auth, expert = token(client), token(client,'expert')
    original = create_record(client, auth)
    create_record(client, auth, '黄龙病')
    path = BASE + '/' + original['record_id']
    body = dict(expected_version=0, name='黄龙病', note='叶片特征与初判不符')
    assert client.patch(path + '/correction', headers=auth, json=body).status_code == 403
    corrected = client.patch(path + '/correction', headers=expert, json=body).json()
    assert corrected['correction_version'] == 1 and corrected['recognition'] == original['recognition']
    assert corrected['correction_events'][0]['from_name'] == '溃疡病'
    assert client.patch(path + '/correction', headers=expert, json=body).status_code == 409
    assert client.get(path, headers=auth).json()['current_name'] == '黄龙病'
    assert client.get(BASE, headers=expert, params={'names':'溃疡病'}).json()['total'] == 0
    assert client.get(BASE, headers=expert, params=[('names','黄龙病'),('names','溃疡病')]).json()['total'] == 2
    assert client.get(BASE, headers=expert, params={'status':'corrected','names':'黄龙病'}).json()['total'] == 1
    assert client.get(BASE, headers=expert, params={'query':'采集员甲'}).json()['total'] == 2
    assert client.get(BASE, headers=expert, params={'query':'%'}).json()['total'] == 0
    assert client.get(BASE, headers=expert).json()['categories'] == ['黄龙病']
    assert client.patch(path + '/correction', headers=expert, json={**body,'expected_version':1,'class_id':'invalid'}).status_code == 422


def test_date_range_is_aware_half_open_and_upload_time(client):
    auth, expert = token(client), token(client,'expert')
    record = create_record(client, auth)
    with client.app.state.storage.transaction() as store:
        store.get_offline(record['record_id'])['uploaded_at'] = '2026-11-03T16:00:00Z'
    before = client.get(BASE, headers=expert, params={'uploaded_from':'2026-11-02T16:00:00Z','uploaded_to':'2026-11-03T16:00:00Z'})
    assert before.json()['total'] == 0
    assert client.get(BASE, headers=expert, params={'uploaded_from':'2026-11-04T00:00:00+08:00'}).json()['total'] == 1
    assert client.get(BASE, headers=expert, params={'uploaded_from':'2026-11-03T00:00:00'}).status_code == 422
    assert client.get(BASE, headers=expert, params={'uploaded_from':'2026-11-04T00:00:00Z','uploaded_to':'2026-11-03T00:00:00Z'}).status_code == 422
