"""账号管理接口测试（仅 super_admin；进程内状态，无网络）。

三个场景：完整生命周期与会话撤销、重置密码使旧凭据失效、权限与自我保护。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app.main import create_app

BASE = "/api/v1"
USERS = "/api/v1/admin/users"
PASSWORD = "12345678"


@pytest.fixture()
def app():
    # 显式内存存储：测试之间完全隔离，不读写本地数据库文件。
    return create_app("memory")


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str = "super", password: str = PASSWORD) -> dict:
    resp = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error_of(resp) -> dict:
    body = resp.json()
    assert set(body) == {"error"}, body
    return body["error"]


def test_create_edit_disable_reenable_does_not_restore_sessions(client: TestClient):
    super_session = login(client, "super")
    headers = bearer(super_session["access_token"])

    created = client.post(
        USERS,
        headers=headers,
        json={"username": "collector9", "display_name": "  采集九  ", "role": "collector"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    user = body["user"]
    assert user["username"] == "collector9"
    assert user["display_name"] == "采集九"
    assert user["role"] == "collector"
    assert user["is_active"] is True
    assert user["last_login_at"] is None
    assert user["created_at"].endswith("Z")
    assert len(body["temporary_password"]) >= 12
    assert "password" not in user

    # 临时密码可直接登录
    target = login(client, "collector9", body["temporary_password"])
    target_headers = bearer(target["access_token"])
    assert client.get(f"{BASE}/me", headers=target_headers).json()["role"] == "collector"

    # 列表为真实分页数据，含新账号且不泄露密码
    page = client.get(USERS, headers=headers, params={"page": 1, "page_size": 20}).json()
    assert page["total"] >= 6
    assert page["page"] == 1 and page["page_size"] == 20
    assert any(row["username"] == "collector9" for row in page["items"])
    assert all("password" not in row for row in page["items"])

    uid = user["user_id"]

    # 只改显示名：不清会话
    renamed = client.patch(f"{USERS}/{uid}", headers=headers, json={"display_name": "采集九号"})
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "采集九号"
    assert client.get(f"{BASE}/me", headers=target_headers).status_code == 200

    # 停用：目标账号旧令牌立即失效
    disabled = client.patch(f"{USERS}/{uid}", headers=headers, json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert client.get(f"{BASE}/me", headers=target_headers).status_code == 401

    # 重新启用不恢复旧会话，但可用原密码重新登录
    enabled = client.patch(f"{USERS}/{uid}", headers=headers, json={"is_active": True})
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    assert client.get(f"{BASE}/me", headers=target_headers).status_code == 401
    fresh = login(client, "collector9", body["temporary_password"])
    assert client.get(f"{BASE}/me", headers=bearer(fresh["access_token"])).status_code == 200


def test_reset_password_invalidates_old_password_and_sessions(client: TestClient):
    headers = bearer(login(client, "super")["access_token"])

    created = client.post(
        USERS,
        headers=headers,
        json={"username": "collector8", "display_name": "采集八", "role": "collector"},
    )
    assert created.status_code == 201, created.text
    uid = created.json()["user"]["user_id"]
    old_password = created.json()["temporary_password"]

    target_headers = bearer(login(client, "collector8", old_password)["access_token"])

    reset = client.post(f"{USERS}/{uid}/reset-password", headers=headers)
    assert reset.status_code == 200
    new_password = reset.json()["temporary_password"]
    assert new_password != old_password
    assert len(new_password) >= 12

    # 旧令牌立即失效
    assert client.get(f"{BASE}/me", headers=target_headers).status_code == 401
    # 旧密码不能登录
    stale = client.post(f"{BASE}/auth/login", json={"username": "collector8", "password": old_password})
    assert stale.status_code == 401
    assert error_of(stale)["details"]["reason"] == "bad_credentials"
    # 新密码可登录，is_active 未变
    login(client, "collector8", new_password)
    page = client.get(USERS, headers=headers, params={"page": 1, "page_size": 50}).json()
    row = next(u for u in page["items"] if u["user_id"] == uid)
    assert row["is_active"] is True


def test_permissions_validation_and_self_protection(client: TestClient):
    # 普通 admin 无权访问任何账号端点
    admin_headers = bearer(login(client, "admin")["access_token"])
    assert client.get(USERS, headers=admin_headers).status_code == 403
    assert error_of(client.get(USERS, headers=admin_headers))["code"] == "FORBIDDEN"
    assert (
        client.post(
            USERS,
            headers=admin_headers,
            json={"username": "collector7", "display_name": "采集七", "role": "collector"},
        ).status_code
        == 403
    )

    super_session = login(client, "super")
    headers = bearer(super_session["access_token"])
    super_id = super_session["user"]["user_id"]

    # 重复登录名
    duplicate = client.post(
        USERS, headers=headers, json={"username": "admin", "display_name": "重复", "role": "admin"}
    )
    assert duplicate.status_code == 409
    assert error_of(duplicate)["code"] == "STATE_CONFLICT"

    # 未知写字段 / 非法登录名
    unknown_field = client.post(
        USERS,
        headers=headers,
        json={"username": "collector7", "display_name": "采集七", "role": "collector", "orchard_ids": []},
    )
    assert unknown_field.status_code == 422
    assert error_of(unknown_field)["code"] == "VALIDATION_FAILED"
    assert (
        client.post(USERS, headers=headers, json={"username": "Bad", "display_name": "x", "role": "collector"}).status_code
        == 422
    )

    # 空 PATCH 与显式 null 都无效；未知账号 404
    assert client.patch(f"{USERS}/{super_id}", headers=headers, json={}).status_code == 422
    assert client.patch(f"{USERS}/{super_id}", headers=headers, json={"display_name": None}).status_code == 422
    assert (
        client.patch(
            f"{USERS}/019a0000-0000-7000-8000-0000000000ff", headers=headers, json={"display_name": "无人"}
        ).status_code
        == 404
    )

    # 当前账号保护：不能停用自己、不能给自己降级，但可以改自己的显示名
    assert client.patch(f"{USERS}/{super_id}", headers=headers, json={"is_active": False}).status_code == 409
    assert client.patch(f"{USERS}/{super_id}", headers=headers, json={"role": "admin"}).status_code == 409
    renamed = client.patch(f"{USERS}/{super_id}", headers=headers, json={"display_name": "超级管理员甲"})
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "超级管理员甲"
