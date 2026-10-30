import json
import pytest
from fastapi.testclient import TestClient
from server.app.main import create_app
from server.app.common import new_uuid7
from server.tests.test_recognition import Classifier, token, png


def submit(client, auth, **query):
    return client.post('/api/v1/diagnoses', params=query, headers={**auth, 'Content-Type': 'image/png', 'X-Image-ID': new_uuid7()}, content=png())


def entry(**kw):
    return dict(class_id='citrus_canker', approved=True, crop_ids=['huyou'], parts=['leaf'], tree_ages=['adult'], title='测试资料', message='仅测试规则', actions=[{'title':'测试动作', 'detail':'测试说明'}], sources=[{'title':'测试来源', 'url':'https://example.org/reference'}], **kw)


def test_empty_and_retry_and_security(monkeypatch):
    monkeypatch.delenv('APP_DIAGNOSIS_KNOWLEDGE', raising=False)
    classifier = Classifier()
    with TestClient(create_app('memory', recognizer=classifier)) as client:
        assert submit(client, {}).status_code == 401
        assert submit(client, token(client, 'admin')).status_code == 403
        auth = token(client)
        assert submit(client, auth, part='invalid').status_code == 422
        result = submit(client, auth).json()
        assert result['advice']['status'] == 'unavailable'
        receipt = result['receipt']
        assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt': receipt}).json() == result['advice']
        assert len(classifier.calls) == 1
        for value in [receipt+'x', 'junk', receipt.split('.')[0]+'.AAAA']:
            assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt':value}).status_code == 422
        assert client.post('/api/v1/diagnoses/advice', headers=token(client, 'collector2'), json={'receipt':receipt}).status_code == 403
        assert client.get('/api/v1/samples', headers=auth).json()['total'] == 0


def test_unconfigured_model(monkeypatch):
    monkeypatch.delenv('APP_RECOGNITION_PYTHON', raising=False)
    monkeypatch.delenv('APP_RECOGNITION_MANIFEST', raising=False)
    with TestClient(create_app('memory')) as client:
        assert submit(client, token(client)).status_code == 503


@pytest.mark.parametrize('case,expected', [('matched','matched'),('low','uncertain'),('close','uncertain'),('unapproved','unmapped'),('unmapped','unmapped'),('part','conflict'),('crop','conflict'),('age','conflict'),('scope','conflict'),('duplicate','conflict'),('healthy','healthy'),('badfile','unavailable'),('nosource','unavailable')])
def test_knowledge_branches(tmp_path, monkeypatch, case, expected):
    source = tmp_path / 'knowledge.json'
    item = entry()
    classifier = Classifier()
    raw = classifier.predict(b'')
    if case == 'low': raw['candidates'][0]['score'] = .4
    if case == 'close': raw['candidates'][1]['score'] = .77
    if case == 'unapproved': item['approved'] = False
    if case == 'unmapped': raw['candidates'][0]['class_id'] = None
    if case == 'part': item['parts'] = ['fruit']
    if case == 'crop': item['crop_ids'] = ['xiangyou']
    if case == 'age': item['tree_ages'] = ['young']
    if case == 'scope': raw['scope'] = 'fruit'
    if case == 'healthy': item['kind'] = 'healthy'; item['actions'] = []
    if case == 'nosource': item['sources'] = []
    source.write_text(json.dumps({'version':'test-1','entries':[item,item] if case == 'duplicate' else [item]}))
    if case == 'badfile': source.write_text('broken')
    monkeypatch.setenv('APP_DIAGNOSIS_KNOWLEDGE', str(source))
    classifier.predict = lambda data: raw
    with TestClient(create_app('memory', recognizer=classifier)) as client:
        advice = submit(client, token(client), crop_id='huyou', part='leaf', tree_age='adult').json()['advice']
        assert advice['status'] == expected
        assert bool(advice['actions']) == (expected == 'matched')


def test_retry_reads_current_knowledge_and_rejects_expired_receipt(tmp_path, monkeypatch):
    from server.app.diagnosis import verify, sign
    path = tmp_path / 'knowledge.json'
    monkeypatch.setenv('APP_DIAGNOSIS_KNOWLEDGE', str(path))
    with TestClient(create_app('memory', recognizer=Classifier())) as client:
        auth = token(client)
        result = submit(client, auth, tree_age='adult').json()
        assert result['advice']['status'] == 'unavailable'
        path.write_text(json.dumps({'version':'new', 'entries':[entry()]}))
        response = client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt':result['receipt']})
        assert response.json()['status'] == 'matched'
        user = client.get('/api/v1/me', headers=auth).json()['user_id']
        payload = verify(result['receipt'], client.app.state.diagnosis_key, user)
        payload.expires = 1
        expired = sign(payload, client.app.state.diagnosis_key)
        assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt':expired}).status_code == 422
        assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt':result['receipt'], 'class_id':'fake'}).status_code == 422
        client.app.state.store.classes[0]['is_active'] = False
        for row in client.app.state.store.classes:
            if row['class_id'] == 'citrus_canker': row['is_active'] = False
        assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt':result['receipt']}).json()['status'] == 'unmapped'


def test_receipt_signing_key_persists_and_is_private(tmp_path, monkeypatch):
    from server.app.diagnosis import signing_key
    monkeypatch.delenv('APP_DIAGNOSIS_SECRET', raising=False)
    assert signing_key(tmp_path) == signing_key(tmp_path)
    assert (tmp_path / 'diagnosis-secret').stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv('APP_DIAGNOSIS_SECRET', 'short')
    with pytest.raises(RuntimeError): signing_key(tmp_path)


def test_diagnosis_reuses_image_validation_and_unknown_age_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / 'knowledge.json'
    path.write_text(json.dumps({'version':'test','entries':[entry()]}))
    monkeypatch.setenv('APP_DIAGNOSIS_KNOWLEDGE', str(path))
    with TestClient(create_app('memory', recognizer=Classifier())) as client:
        auth = token(client)
        assert submit(client, auth).json()['advice']['status'] == 'conflict'
        headers = {**auth, 'X-Image-ID':new_uuid7(), 'Content-Type':'image/png'}
        assert client.post('/api/v1/diagnoses', headers=headers, content=b'broken').status_code == 415
        assert client.post('/api/v1/diagnoses', headers={**headers,'X-Image-ID':'bad'}, content=png()).status_code == 422
