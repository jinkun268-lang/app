import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server.app.common import DomainError, new_uuid7
from server.app.data_access import StorageUnavailable
from server.app.main import create_app
from server.tests.test_recognition import Classifier, png, token

BASE = '/api/v1/offline-recognitions'


def inputs():
    return dict(crop_id='huyou', part='leaf', tree_age='adult', symptom='现场现象', captured_at='2026-11-03T08:00:00+08:00',
                mime_type='image/png', file_size=len(png()), sha256=hashlib.sha256(png()).hexdigest())


def post(client, auth, rid, data=None):
    return client.post('/api/v1/diagnoses', params={'crop_id':'huyou','part':'leaf','tree_age':'adult'},
        headers={**auth, 'X-Image-ID':rid, 'Content-Type':'image/png'}, content=png() if data is None else data)


@pytest.fixture(params=['memory', 'sqlite'])
def context(request, tmp_path):
    url = 'memory' if request.param == 'memory' else f'sqlite+pysqlite:///{tmp_path / "db.sqlite3"}'
    model = Classifier()
    app = create_app(url, recognizer=model, storage_root=tmp_path)
    with TestClient(app) as client:
        yield client, model, tmp_path, url


def test_picture_and_default_record_exist_before_model_and_real_result_replaces_same_row(context):
    client, model, folder, _ = context
    auth, expert = token(client), token(client, 'expert')
    rid = new_uuid7()
    assert client.put(f'/api/v1/diagnoses/{rid}', headers=auth, json=inputs()).json()['current_name'] == '系统识别错误'
    entered, release = threading.Event(), threading.Event()
    original = model.predict
    def predict(data):
        entered.set(); assert release.wait(5)
        return original(data)
    model.predict = predict
    with ThreadPoolExecutor() as pool:
        future = pool.submit(post, client, auth, rid)
        try:
            assert entered.wait(5)
            record = client.get(BASE, headers=expert).json()['items'][0]
            assert record['record_id'] == rid and record['current_name'] == '系统识别错误'
            assert record['inference_status'] == 'processing' and record['recognition'] is None
            assert client.get(record['image_url'], headers=expert).content == png()
            assert (folder / 'files' / 'originals' / f'{rid}.png').read_bytes() == png()
            assert post(client, auth, rid).status_code == 409
            assert client.patch(f'{BASE}/{rid}/correction', headers=expert, json={'expected_version':0,'name':'人工结果'}).status_code == 409
        finally:
            release.set()
        result = future.result()
    assert result.status_code == 200, result.text
    record = client.get(f'{BASE}/{rid}', headers=expert).json()
    assert record['inference_status'] == 'succeeded' and record['current_name'] == '溃疡病'
    assert record['symptom'] == '现场现象'
    assert record['recognition'] == result.json()['recognition']
    assert client.get(BASE, headers=expert).json()['total'] == 1
    assert post(client, auth, rid).json()['recognition'] == result.json()['recognition']
    assert len(model.calls) == 1
    assert client.get(f'/api/v1/diagnoses/{rid}', headers=auth).json()['result']['recognition'] == result.json()['recognition']


def test_failure_keeps_picture_and_default_without_phone_followup_then_retry_preserves_human_correction(context):
    client, model, _, _ = context
    auth, expert = token(client), token(client, 'expert')
    rid = new_uuid7(); original = model.predict
    def unavailable(data):
        raise DomainError(503, 'MODEL_UNAVAILABLE', '模型不可用')
    model.predict = unavailable
    result = post(client, auth, rid)
    assert result.status_code == 503
    record = client.get(f'{BASE}/{rid}', headers=expert).json()
    assert record['state'] == 'complete' and record['inference_status'] == 'failed'
    assert record['current_name'] == '系统识别错误' and record['recognition'] is None
    assert record['inference_error_code'] == 'MODEL_UNAVAILABLE'
    assert client.get(record['image_url'], headers=expert).content == png()
    assert client.get(f'/api/v1/diagnoses/{rid}', headers=auth).json()['result'] is None
    assert client.patch(f'{BASE}/{rid}/correction', headers=expert, json={'expected_version':0,'name':'人工结果'}).status_code == 200
    model.predict = original
    assert post(client, auth, rid).status_code == 200
    updated = client.get(f'{BASE}/{rid}', headers=expert).json()
    assert updated['current_name'] == '人工结果' and updated['correction_version'] == 1
    assert updated['recognition']['candidates'][0]['name'] == '溃疡病'


def test_reference_is_committed_before_publication_and_file_failure_never_calls_model(context, monkeypatch):
    client, model, _, _ = context
    auth = token(client); rid = new_uuid7()
    files = client.app.state.files
    publish = files.write
    def failing_publish(key, data):
        with client.app.state.storage.transaction(write=False) as store:
            row = store.get_offline(rid)
            assert row['file_key'] == key and row['current_name'] == '系统识别错误'
        raise StorageUnavailable('测试保存失败')
    monkeypatch.setattr(files, 'write', failing_publish)
    assert post(client, auth, rid).status_code == 503
    assert not model.calls
    with client.app.state.storage.transaction(write=False) as store:
        assert store.get_offline(rid)['inference_status'] == 'failed'
    monkeypatch.setattr(files, 'write', publish)
    assert post(client, auth, rid).status_code == 200
    assert len(model.calls) == 1


def test_result_commit_failure_retains_referenced_picture(context, monkeypatch):
    from server.app import diagnosis_records
    client, _, _, _ = context
    auth = token(client); rid = new_uuid7()
    def unavailable(*args):
        raise StorageUnavailable('测试结果写入失败')
    monkeypatch.setattr(diagnosis_records, 'succeed', unavailable)
    assert post(client, auth, rid).status_code == 503
    record = client.get(f'{BASE}/{rid}', headers=token(client,'expert')).json()
    assert record['inference_status'] == 'failed' and record['current_name'] == '系统识别错误'
    assert client.get(record['image_url'], headers=auth).content == png()


def test_owner_idempotency_and_invalid_image(context):
    client, model, folder, _ = context
    auth, other = token(client), token(client,'collector2')
    rid = new_uuid7()
    assert client.put(f'/api/v1/diagnoses/{rid}', headers=auth, json=inputs()).status_code == 200
    assert client.put(f'/api/v1/diagnoses/{rid}', headers=other, json=inputs()).status_code == 404
    changed = {**inputs(), 'symptom':'改动'}
    assert client.put(f'/api/v1/diagnoses/{rid}', headers=auth, json=changed).status_code == 409
    assert post(client, other, rid).status_code == 404
    assert client.get(f'/api/v1/diagnoses/{rid}', headers=other).status_code == 404
    assert post(client, auth, rid, b'broken').status_code == 415
    assert not model.calls and not (folder / 'files' / 'originals' / f'{rid}.png').exists()
    assert client.get(BASE, headers=token(client,'expert')).json()['total'] == 0


def test_sqlite_restart_recovers_interrupted_record_and_keeps_original(tmp_path):
    url = f'sqlite+pysqlite:///{tmp_path / "data.sqlite3"}'
    rid = new_uuid7()
    with TestClient(create_app(url, recognizer=Classifier(), storage_root=tmp_path)) as client:
        assert post(client, token(client), rid).status_code == 200
        with client.app.state.storage.transaction() as store:
            row = store.get_offline(rid)
            row['declaration'] = {**row['declaration'], 'recognition':None}
            row.update(inference_status='processing', current_name='系统识别错误')
    with TestClient(create_app(url, storage_root=tmp_path)) as client:
        auth = token(client)
        row = client.get(f'{BASE}/{rid}', headers=auth).json()
        assert row['inference_status'] == 'failed' and row['inference_error_code'] == 'INFERENCE_INTERRUPTED'
        assert row['current_name'] == '系统识别错误' and row['recognition'] is None
        assert client.get(row['image_url'], headers=auth).content == png()
