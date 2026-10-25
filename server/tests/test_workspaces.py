"""Workspace permissions and owner pagination against both storage implementations."""
import pytest
from fastapi.testclient import TestClient

from server.app.main import create_app
from server.app.common import new_uuid7
from test_uploads import BASE, bearer, declaration, declare, image_decl, login, png_bytes, put_image


@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
def test_owner_scope_precedes_pagination_and_role_writes(backend, tmp_path):
    app = (create_app('memory') if backend == 'memory' else create_app(
        database_url=f'sqlite+pysqlite:///{(tmp_path / "db.sqlite").as_posix()}',
        storage_root=tmp_path / 'media', seed_demo=True))
    with TestClient(app) as client:
        owner = login(client, 'collector1')
        other = login(client, 'collector2')
        expert = login(client, 'expert')
        admin = login(client, 'admin')
        ids = []
        for token in [owner, other, other]:
            image = image_decl(new_uuid7(), png_bytes(8, 6), 'image/png', 8, 6)
            sid = new_uuid7()
            upload = declare(client, token, declaration(sid, image))
            assert put_image(client, token, upload['upload_id'], image, png_bytes(8, 6)).status_code == 201
            assert client.post(f'{BASE}/uploads/{upload["upload_id"]}/complete', headers=bearer(token)).status_code == 200
            ids.append((sid, image['image_id']))
        page = client.get(f'{BASE}/samples?page_size=1&owner_id=ignored', headers=bearer(owner)).json()
        assert page['total'] == 1
        assert page['items'][0]['sample_id'] == ids[0][0]
        assert client.get(f'{BASE}/samples?page_size=1&page=2', headers=bearer(owner)).json()['items'] == []
        assert client.get(f'{BASE}/samples/{ids[1][0]}', headers=bearer(owner)).status_code == 404
        assert client.get(f'{BASE}/samples', headers=bearer(expert)).json()['total'] == 3
        sid, iid = ids[0]
        quality = f'{BASE}/samples/{sid}/images/{iid}/quality'
        review = f'{BASE}/samples/{sid}/review'
        body = {'expected_version': 0, 'quality_status': 'usable'}
        assert client.patch(quality, headers=bearer(admin), json=body).status_code == 409
        assert client.patch(quality, headers=bearer(expert), json=body).status_code == 403
        assert client.patch(review, headers=bearer(admin), json={'expected_version': 0, 'review_status': 'confirmed'}).status_code == 403
        approved = client.patch(review, headers=bearer(expert), json={
            'expected_version': 0, 'review_status': 'corrected', 'final_cultivar_id': 'huyou',
            'final_part': 'leaf', 'final_class_id': 'citrus_canker'})
        assert approved.status_code == 200, approved.text
        assert client.patch(quality, headers=bearer(admin), json=body).status_code == 200
        assert client.get(f'{BASE}/media/sample-images/{iid}', headers=bearer(expert)).status_code == 200
        assert client.get(f'{BASE}/exports', headers=bearer(expert)).status_code == 403
