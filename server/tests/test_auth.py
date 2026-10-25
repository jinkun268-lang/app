"""认证与配置接口测试（进程内状态，无需真实服务或网络）。

期限相关用例直接改 app.state.store.sessions，不 sleep。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from server.app.common import utcnow
from server.app.main import create_app

BASE = "/api/v1"
PASSWORD = "12345678"


@pytest.fixture()
def app():
    # 显式内存存储：测试之间完全隔离，不读写本地数据库文件。
    return create_app("memory")


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str = "admin", password: str = PASSWORD) -> dict:
    resp = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error_of(resp) -> dict:
    body = resp.json()
    assert set(body) == {"error"}, body
    return body["error"]


def test_health_and_ready(client: TestClient):
    for path in ("/api/v1/health", "/api/v1/health/ready"):
        resp = client.get(path)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == "2.0.0"
        assert body["time"].endswith("Z")


def test_login_success_and_me(client: TestClient):
    data = login(client)
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 1800
    assert data["access_token"] and data["refresh_token"]
    assert data["access_token"] != data["refresh_token"]
    assert data["user"] == {
        "user_id": "019a0000-0000-7000-8000-000000000002",
        "username": "admin",
        "display_name": "管理员",
        "role": "admin",
    }
    # 响应绝不包含密码
    assert "password" not in str(data["user"])

    me = client.get(f"{BASE}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200
    assert me.json() == data["user"]


def test_collector_can_login(client: TestClient):
    data = login(client, "collector1")
    assert data["user"]["role"] == "collector"
    me = client.get(f"{BASE}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200
    assert me.json()["role"] == "collector"


def test_bad_credentials_are_uniform(client: TestClient):
    wrong_password = client.post(f"{BASE}/auth/login", json={"username": "admin", "password": "x"})
    unknown_user = client.post(f"{BASE}/auth/login", json={"username": "nobody", "password": "x"})
    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    a, b = error_of(wrong_password), error_of(unknown_user)
    assert a["code"] == b["code"] == "AUTH_INVALID"
    assert a["details"]["reason"] == b["details"]["reason"] == "bad_credentials"
    assert a["message"] == b["message"]
    assert a["request_id"] and "Traceback" not in wrong_password.text


def test_refresh_rotates_and_old_tokens_invalid(client: TestClient):
    first = login(client)
    refreshed = client.post(f"{BASE}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200
    second = refreshed.json()
    assert second["token_type"] == "Bearer"
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]

    # 新访问令牌可用
    ok = client.get(f"{BASE}/me", headers=bearer(second["access_token"]))
    assert ok.status_code == 200
    # 旧刷新令牌已被轮换失效
    again = client.post(f"{BASE}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert again.status_code == 401
    assert error_of(again)["details"]["reason"] == "revoked"
    # 旧访问令牌随会话撤销
    old = client.get(f"{BASE}/me", headers=bearer(first["access_token"]))
    assert old.status_code == 401


def test_logout_revokes_access_and_refresh(client: TestClient):
    data = login(client)
    out = client.post(f"{BASE}/auth/logout", headers=bearer(data["access_token"]))
    assert out.status_code == 204
    assert out.content == b""

    me = client.get(f"{BASE}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 401
    err = error_of(me)
    assert err["code"] == "AUTH_INVALID"
    assert err["details"]["reason"] == "revoked"

    refresh = client.post(f"{BASE}/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refresh.status_code == 401
    assert error_of(refresh)["details"]["reason"] == "revoked"


def test_expired_access_has_exact_code_and_reason(client: TestClient):
    data = login(client)
    record = client.app.state.store.sessions[data["access_token"]]
    record["expires_at"] = utcnow() - timedelta(seconds=1)

    me = client.get(f"{BASE}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 401
    err = error_of(me)
    # 客户端只按 code+details.reason 触发刷新，二者必须精确
    assert err["code"] == "AUTH_INVALID"
    assert err["details"]["reason"] == "expired"

    # 刷新令牌仍然有效，可换回可用访问令牌
    refreshed = client.post(f"{BASE}/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.get(f"{BASE}/me", headers=bearer(refreshed.json()["access_token"])).status_code == 200


def test_missing_token_is_auth_required(client: TestClient):
    resp = client.get(f"{BASE}/me")
    assert resp.status_code == 401
    err = error_of(resp)
    assert err["code"] == "AUTH_REQUIRED"


def test_disabled_account_blocks_login_and_existing_session(client: TestClient):
    data = login(client)
    store = client.app.state.store
    next(u for u in store.users if u["username"] == "admin")["is_active"] = False

    denied = client.post(f"{BASE}/auth/login", json={"username": "admin", "password": PASSWORD})
    assert denied.status_code == 403
    assert error_of(denied)["code"] == "ACCOUNT_DISABLED"

    me = client.get(f"{BASE}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 403
    assert error_of(me)["code"] == "ACCOUNT_DISABLED"


def test_bootstrap_has_no_orchards(client: TestClient):
    data = login(client)
    resp = client.get(f"{BASE}/config/bootstrap", headers=bearer(data["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert "orchards" not in body
    assert set(body) == {"cultivars", "classes", "taxonomy_version", "policy_version", "server_time"}
    assert body["taxonomy_version"] >= 1
    assert body["policy_version"] >= 1
    assert body["server_time"].endswith("Z")

    cultivar_ids = [c["cultivar_id"] for c in body["cultivars"]]
    assert {"unknown", "huyou", "xiangyou"} <= set(cultivar_ids)
    classes = {c["class_id"]: c for c in body["classes"]}
    assert classes["citrus_canker"]["is_provisional"] is False
    assert classes["unknown"]["is_active"] is True
    for row in body["classes"]:
        assert {"parent_id", "version", "introduced_taxonomy_version"} <= set(row)


def test_uniform_error_shape_for_unknown_route_and_validation(client: TestClient):
    rid = "019a0000-0000-7000-8000-0000000000aa"
    missing = client.get("/api/v1/does-not-exist", headers={"X-Request-Id": rid})
    assert missing.status_code == 404
    assert missing.headers["X-Request-Id"] == rid
    assert missing.headers["Cache-Control"] == "no-store"
    err = error_of(missing)
    assert err["code"] == "NOT_FOUND"
    assert err["request_id"] == rid
    assert "message" in err

    invalid = client.post(f"{BASE}/auth/login", json={})
    assert invalid.status_code == 422
    err = error_of(invalid)
    assert err["code"] == "VALIDATION_FAILED"
    assert err["details"]["fields"]
    assert {"field", "reason"} <= set(err["details"]["fields"][0])


def test_two_apps_do_not_share_state():
    app_a, app_b = create_app("memory"), create_app("memory")
    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        data = login(client_a)
        assert client_a.get(f"{BASE}/me", headers=bearer(data["access_token"])).status_code == 200
        # B 进程内没有 A 的会话
        foreign = client_b.get(f"{BASE}/me", headers=bearer(data["access_token"]))
        assert foreign.status_code == 401
        assert error_of(foreign)["details"]["reason"] == "revoked"
        assert client_b.app.state.store.sessions == {}
        assert client_a.app.state.store.sessions is not client_b.app.state.store.sessions
