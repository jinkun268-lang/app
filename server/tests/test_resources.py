"""Concurrency admission, a responsive event loop and bounded immutable exports."""
import asyncio
from dataclasses import replace
import threading

import anyio
from fastapi.testclient import TestClient
import httpx
import pytest

from server.app import exports, uploads
from server.app.common import new_uuid7
from server.app.main import create_app
from server.app.resources import ServiceLimits
from test_flow import review_and_qualify, upload_two_images, wait_export
from test_uploads import BASE, bearer, declaration, image_decl, login, png_bytes


def test_decode_does_not_block_health_and_uploads_reject_when_full(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    verify = uploads._verify_decodable

    def held_decode(*args):
        entered.set()
        assert release.wait(8), 'test decode was not released'
        return verify(*args)

    monkeypatch.setattr(uploads, '_verify_decodable', held_decode)

    async def scenario():
        app = create_app('memory', limits=ServiceLimits(upload_concurrency=1))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                session = (await client.post(BASE+'/auth/login', json={
                    'username': 'collector1', 'password': '12345678'})).json()
                owner = bearer(session['access_token'])
                raw = png_bytes(8, 6)
                image = image_decl(new_uuid7(), raw, 'image/png', 8, 6)
                declared = await client.post(BASE+'/uploads', headers=owner,
                                            json=declaration(new_uuid7(), image))
                assert declared.status_code == 201
                url = f'{BASE}/uploads/{declared.json()["upload_id"]}/images/{image["image_id"]}'
                headers = {**owner, 'content-type': 'image/png', 'x-content-sha256': image['sha256']}
                pending = asyncio.create_task(client.put(url, headers=headers, content=raw))
                try:
                    assert await anyio.to_thread.run_sync(entered.wait, 3)
                    health = await asyncio.wait_for(client.get(BASE+'/health'), 2)
                    assert health.status_code == 200
                    rejected = await asyncio.wait_for(client.put(url, headers=headers, content=raw), 2)
                    assert rejected.status_code == 429
                    assert rejected.headers['retry-after'] == '2'
                finally:
                    release.set()
                    assert (await pending).status_code == 201
                # The permit is released and the immutable upload receipt can be replayed.
                assert (await client.put(url, headers=headers, content=raw)).status_code == 200

    anyio.run(scenario)


def test_export_admission_keeps_replay_available_and_releases_after_failure(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = exports._write_zip

    def fail_once(*args):
        entered.set()
        assert release.wait(8)
        raise OSError('simulated disk failure')

    monkeypatch.setattr(exports, '_write_zip', fail_once)
    with TestClient(create_app('memory')) as client:
        admin = login(client, 'admin')
        headers = {**bearer(admin), 'Idempotency-Key': new_uuid7()}
        first = client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'})
        assert first.status_code == 202
        try:
            assert entered.wait(3)
            denied = client.post(BASE+'/exports', headers={**headers, 'Idempotency-Key': new_uuid7()},
                                 json={'format': 'dataset'})
            assert denied.status_code == 429 and int(denied.headers['retry-after']) > 0
            replay = client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'})
            assert replay.status_code == 202 and replay.json()['export_id'] == first.json()['export_id']
            assert client.get(BASE+'/health').status_code == 200
        finally:
            release.set()
        job = wait_export(client, admin, first.json()['export_id'])
        assert job['status'] == 'failed' and job['zip_size'] is None
        monkeypatch.setattr(exports, '_write_zip', original)
        retried = client.post(BASE+'/exports/'+job['export_id']+'/retry',
                              headers={**headers, 'Idempotency-Key': new_uuid7()})
        assert retried.status_code == 202
        assert wait_export(client, admin, job['export_id'])['status'] == 'succeeded'


@pytest.mark.parametrize('setting', ['export_max_bytes', 'export_max_images'])
def test_oversized_snapshot_creates_no_job_and_does_not_consume_admission(setting):
    with TestClient(create_app('memory')) as client:
        info = upload_two_images(client)
        admin = login(client, 'admin')
        review_and_qualify(client, admin, info)
        # Qualify the second image as well, so the image-count limit is meaningful.
        assert client.patch(f'{BASE}/samples/{info["sample_id"]}/images/{info["b"]["image_id"]}/quality',
                            headers=bearer(admin), json={'expected_version': 1, 'quality_status': 'usable'}).status_code == 200
        limits = client.app.state.limits
        client.app.state.limits = replace(limits, **{setting: 1})
        key = new_uuid7()
        headers = {**bearer(admin), 'Idempotency-Key': key}
        denied = client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'})
        assert denied.status_code == 413
        assert client.get(BASE+'/exports', headers=bearer(admin)).json()['total'] == 0
        client.app.state.limits = limits
        accepted = client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'})
        assert accepted.status_code == 202
        assert wait_export(client, admin, accepted.json()['export_id'])['item_count'] == 2


def test_export_rate_limit_does_not_reject_existing_idempotent_job():
    with TestClient(create_app('memory', limits=ServiceLimits(export_requests_per_minute=1))) as client:
        admin = login(client, 'admin')
        headers = {**bearer(admin), 'Idempotency-Key': new_uuid7()}
        first = client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'})
        assert first.status_code == 202
        wait_export(client, admin, first.json()['export_id'])
        assert client.post(BASE+'/exports', headers=headers, json={'format': 'dataset'}).status_code == 202
        limited = client.post(BASE+'/exports', headers={**headers, 'Idempotency-Key': new_uuid7()},
                              json={'format': 'dataset'})
        assert limited.status_code == 429
        assert 1 <= int(limited.headers['retry-after']) <= 60
