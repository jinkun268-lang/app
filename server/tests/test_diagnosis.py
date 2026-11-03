import json
import os
import pytest
from fastapi.testclient import TestClient
from server.app.main import create_app
from server.app.common import new_uuid7
from server.tests.test_recognition import Classifier, token, png


def submit(client, auth, **query):
    return client.post('/api/v1/diagnoses', params=query, headers={**auth, 'Content-Type': 'image/png', 'X-Image-ID': new_uuid7()}, content=png())


def entry(**kw):
    return dict(class_id='citrus_canker', approved=True, crop_ids=['huyou'], parts=['leaf'], tree_ages=['adult'], title='测试资料', message='仅测试规则', actions=[{'title':'测试动作', 'detail':'测试说明'}], sources=[{'title':'测试来源', 'url':'https://example.org/reference'}], **kw)


def test_basic_default_and_retry_and_security(monkeypatch):
    monkeypatch.delenv('APP_DIAGNOSIS_KNOWLEDGE', raising=False)
    classifier = Classifier()
    with TestClient(create_app('memory', recognizer=classifier)) as client:
        assert submit(client, {}).status_code == 401
        assert submit(client, token(client, 'admin')).status_code == 403
        auth = token(client)
        assert submit(client, auth, part='invalid').status_code == 422
        result = submit(client, auth).json()
        assert result['advice']['status'] == 'matched'
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


@pytest.mark.parametrize('label,title,status', [
    ('black_spot', '黑斑病基础建议', 'matched'),
    ('canker', '溃疡病基础建议', 'matched'),
    ('greening', '黄龙病基础建议', 'matched'),
    ('melanose', '黑点病基础建议', 'matched'),
    ('healthy', '健康养护建议', 'healthy'),
])
def test_basic_advice_for_five_labels_without_catalog_mapping(tmp_path, monkeypatch, label, title, status):
    monkeypatch.delenv('APP_DIAGNOSIS_KNOWLEDGE', raising=False)
    classifier = Classifier()
    predict = classifier.predict

    def classify(data):
        raw = predict(data)
        raw['candidates'][0].update(label=label, name='模型显示名', class_id=None)
        return raw

    classifier.predict = classify
    with TestClient(create_app('memory', recognizer=classifier, storage_root=tmp_path)) as client:
        auth = token(client)
        response = submit(client, auth)
        assert response.status_code == 200, response.text
        result = response.json()
        advice = result['advice']
        assert advice['title'] == title and advice['status'] == status
        assert advice['message'] and advice['sources']
        assert advice['version'] == 'basic-2026-11-03'
        assert len(advice['actions']) == (0 if status == 'healthy' else 3)
        assert result['recognition']['candidates'][0]['class_id'] is None
        assert result['recognition']['candidates'][0]['name'] == '模型显示名'
        image_id = result['recognition']['image_id']
        assert client.post('/api/v1/diagnoses/advice', headers=auth, json={'receipt': result['receipt']}).json() == advice
        snapshot = client.get(f'/api/v1/diagnoses/{image_id}', headers=auth).json()
        assert snapshot['result']['advice'] == advice
        cached = client.post('/api/v1/diagnoses', headers={**auth, 'Content-Type': 'image/png', 'X-Image-ID': image_id}, content=png())
        assert cached.json()['advice'] == advice
        assert len(classifier.calls) == 1
        assert client.get('/api/v1/samples', headers=auth).json()['total'] == 0


@pytest.mark.parametrize('label,score,second,scope,part,expected', [
    ('canker', .4, .2, 'leaf', 'leaf', 'uncertain'),
    ('healthy', .8, .77, 'leaf', 'leaf', 'uncertain'),
    ('unknown', .9, .1, 'leaf', 'leaf', 'unmapped'),
    ('canker', .9, .1, 'fruit', 'leaf', 'conflict'),
    ('canker', .9, .1, 'fruit', 'fruit', 'conflict'),
])
def test_basic_advice_keeps_confidence_and_scope_checks(tmp_path, monkeypatch, label, score, second, scope, part, expected):
    monkeypatch.delenv('APP_DIAGNOSIS_KNOWLEDGE', raising=False)
    classifier = Classifier()
    raw = classifier.predict(b'')
    raw['scope'] = scope
    raw['candidates'][0].update(label=label, score=score)
    raw['candidates'][1]['score'] = second
    classifier.predict = lambda _: raw
    with TestClient(create_app('memory', recognizer=classifier, storage_root=tmp_path)) as client:
        response = submit(client, token(client), part=part)
        assert response.status_code == 200, response.text
        advice = response.json()['advice']
        assert advice['status'] == expected and not advice['actions']


def test_basic_advice_uses_highest_scoring_candidate_for_other_citrus(tmp_path, monkeypatch):
    monkeypatch.delenv('APP_DIAGNOSIS_KNOWLEDGE', raising=False)
    classifier = Classifier()
    raw = classifier.predict(b'')
    raw['candidates'][0]['score'] = .1
    raw['candidates'][1].update(label='healthy', score=.9)
    classifier.predict = lambda _: raw
    with TestClient(create_app('memory', recognizer=classifier, storage_root=tmp_path)) as client:
        for crop, age in [('xiangyou', 'young'), ('citrus', 'adult')]:
            advice = submit(client, token(client), crop_id=crop, tree_age=age).json()['advice']
            assert advice['status'] == 'healthy' and not advice['actions']


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
    # Windows stat/chmod does not expose POSIX permission bits; retain this check on Unix.
    if os.name == 'posix':
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
