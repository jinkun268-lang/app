"""采集上传四步协议与媒体接口测试（TestClient + 进程内状态，无需真实服务/网络）。

请求与响应形状尽量用 `contracts/openapi.yaml` 的 Schema 校验，避免逐字段重复断言；
只对任务要求的关键行为（重放、缺图、权限、哈希、预览）写显式断言。
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image, PngImagePlugin

from server.app.common import new_uuid7
from server.app.main import create_app
from server.app.uploads import public_sample

BASE = "/api/v1"
PASSWORD = "12345678"
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"

_DOC: dict[str, Any] | None = None


# ---------------- 夹具与工具 ----------------

@pytest.fixture()
def app():
    # 显式内存存储：测试之间完全隔离，不读写本地数据库文件。
    return create_app("memory")


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str) -> str:
    resp = client.post(f"{BASE}/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _openapi() -> dict[str, Any]:
    global _DOC
    if _DOC is None:
        _DOC = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return _DOC


def check_schema(name: str, instance: Any) -> None:
    """按 contracts/openapi.yaml 中 components/schemas/<name> 校验实例。"""
    doc = _openapi()
    schema = {"$ref": f"#/components/schemas/{name}", "components": doc["components"]}
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, [(list(e.path), e.message) for e in errors[:3]]


def png_bytes(width: int = 8, height: int = 6, color: tuple[int, int, int] = (12, 120, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def png_with_comment(comment: str, width: int = 8, height: int = 6) -> bytes:
    """同尺寸、同字节长度的 PNG，仅 tEXt 内容不同：用于制造“长度相同、哈希不同”的坏字节。"""
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", comment)
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 120, 200)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def jpeg_bytes(width: int = 10, height: int = 7, color: tuple[int, int, int] = (200, 120, 12)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def image_decl(image_id: str, data: bytes, mime_type: str, width: int, height: int,
               captured_at: str = "2026-10-20T09:12:33+08:00") -> dict[str, Any]:
    return {
        "image_id": image_id,
        "view_type": "close_up",
        "captured_at": captured_at,
        "device_timezone": "Asia/Shanghai",
        "device_model": "Pixel 8",
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "file_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def declaration(sample_id: str, *images: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sample_id": sample_id,
        "schema_version": 1,
        "tree_id": "T-001",
        "cultivar_id": "huyou",
        "part": "leaf",
        "class_id": "unknown",
        "symptoms": "叶片出现黄斑",
        "note": None,
        "images": list(images),
    }
    payload.update(overrides)
    return payload


def declare(client: TestClient, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(f"{BASE}/uploads", json=payload, headers=bearer(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    check_schema("UploadStatus", body)
    return body


def put_image(client: TestClient, token: str, upload_id: str, image: dict[str, Any],
              data: bytes, *, content_type: str | None = None):
    headers = {
        **bearer(token),
        "Content-Type": content_type or image["mime_type"],
        "X-Content-SHA256": image["sha256"],
    }
    return client.put(f"{BASE}/uploads/{upload_id}/images/{image['image_id']}", content=data, headers=headers)


def status_of(client: TestClient, token: str, upload_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/uploads/{upload_id}", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    check_schema("UploadStatus", body)
    return body


# ---------------- 主流程 ----------------

def test_full_upload_flow_and_media(client: TestClient):
    owner = login(client, "collector1")
    admin = login(client, "admin")
    other = login(client, "collector2")
    expert = login(client, "expert")

    png, jpg = png_bytes(8, 6), jpeg_bytes(10, 7)
    png_id, jpg_id = new_uuid7(), new_uuid7()
    sample_id = new_uuid7()
    image_png = image_decl(png_id, png, "image/png", 8, 6)
    image_jpg = image_decl(jpg_id, jpg, "image/jpeg", 10, 7)
    payload = declaration(sample_id, image_png, image_jpg)
    check_schema("UploadDeclareRequest", payload)

    created = declare(client, owner, payload)
    upload_id = created["upload_id"]
    assert created["state"] == "receiving"
    assert created["received_images"] == []
    assert created["missing_images"] == [png_id, jpg_id]
    assert created["invalid_images"] == []

    # 恢复入口：未收到任何字节时与声明响应一致
    assert status_of(client, owner, upload_id) == created

    first = put_image(client, owner, upload_id, image_png, png)
    assert first.status_code == 201, first.text
    check_schema("UploadImageReceipt", first.json())
    assert first.json()["sha256"] == image_png["sha256"]
    assert first.json()["receive_status"] == "received"

    # 相同字节重放：200 且回执一致，不重复计数
    replay = put_image(client, owner, upload_id, image_png, png)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert status_of(client, owner, upload_id)["received_images"] == [png_id]

    blocked = client.post(f"{BASE}/uploads/{upload_id}/complete", headers=bearer(owner))
    assert blocked.status_code == 409
    check_schema("ErrorResponse", blocked.json())
    assert blocked.json()["error"]["code"] == "MISSING_IMAGES"
    assert blocked.json()["error"]["details"]["missing"] == [jpg_id]

    second = put_image(client, owner, upload_id, image_jpg, jpg)
    assert second.status_code == 201, second.text

    done = client.post(f"{BASE}/uploads/{upload_id}/complete", headers=bearer(owner))
    assert done.status_code == 200
    check_schema("UploadCompleteResponse", done.json())
    completed_at = done.json()["upload_completed_at"]
    assert done.json()["state"] == "complete"
    assert done.json()["image_count"] == 2

    # 重复 complete：时间与图片数稳定
    again = client.post(f"{BASE}/uploads/{upload_id}/complete", headers=bearer(owner))
    assert again.status_code == 200
    assert again.json()["upload_completed_at"] == completed_at
    assert again.json()["image_count"] == 2

    final = status_of(client, owner, upload_id)
    assert final["state"] == "complete"
    assert final["received_images"] == [png_id, jpg_id]
    assert final["missing_images"] == [] and final["invalid_images"] == []
    assert set(final["received_images"]) | set(final["missing_images"]) | set(final["invalid_images"]) == {
        png_id, jpg_id,
    }

    # 完成后拒绝新字节
    late = put_image(client, owner, upload_id, image_jpg, jpg)
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "STATE_CONFLICT"

    # 原图：字节、MIME、ETag 均与声明一致
    original_url = f"{BASE}/media/sample-images/{png_id}?variant=original"
    original = client.get(original_url, headers=bearer(owner))
    assert original.status_code == 200
    assert original.content == png
    assert original.headers["content-type"] == "image/png"
    assert original.headers["etag"] == image_png["sha256"]

    preview = client.get(f"{BASE}/media/sample-images/{png_id}?variant=preview", headers=bearer(owner))
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(preview.content)) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.width <= 320
        assert rendered.info.get("exif") is None
    # 预览不改动原图字节
    assert client.get(original_url, headers=bearer(owner)).content == png

    # SampleDetail 投影与契约一致，且不含内部字段
    detail = public_sample(client.app.state.store.samples[sample_id])
    check_schema("SampleDetail", detail)
    assert detail["upload_state"] == "complete"
    assert detail["upload_completed_at"] == completed_at
    assert detail["review_status"] == "unreviewed"
    assert detail["review_version"] == 0
    assert detail["excluded"] is False
    assert detail["original_cultivar_id"] == "huyou"
    assert detail["original_cultivar_name"] == "胡柚"
    assert detail["original_class_name"] == "不确定"
    assert detail["images"][0]["quality_status"] == "pending"
    assert detail["images"][0]["quality_version"] == 0
    assert detail["images"][0]["quality_events"] == []
    assert "owner_id" not in detail and "upload_id" not in detail
    assert "sha256" not in detail["images"][0]
    assert "receive_status" not in detail["images"][0]

    # 时间：内部保留客户端原写法，对外统一 UTC，时刻不变
    internal_image = client.app.state.store.samples[sample_id]["images"][0]
    assert internal_image["captured_at"] == "2026-10-20T09:12:33+08:00"
    assert detail["images"][0]["captured_at"] == "2026-10-20T01:12:33Z"

    # 媒体权限：本人与管理员可读，其他 collector 拒绝，expert 可读
    media_url = f"{BASE}/media/sample-images/{png_id}"
    assert client.get(media_url, headers=bearer(admin)).status_code == 200
    assert client.get(media_url, headers=bearer(other)).status_code == 403
    assert client.get(media_url, headers=bearer(expert)).status_code == 200
    assert client.get(media_url).status_code == 401


# ---------------- 声明幂等与归属 ----------------

def test_declaration_replay_conflict_and_ownership(client: TestClient):
    owner = login(client, "collector1")
    other = login(client, "collector2")

    data = png_bytes()
    image = image_decl(new_uuid7(), data, "image/png", 8, 6)
    sample_id = new_uuid7()
    payload = declaration(sample_id, image)

    created = declare(client, owner, payload)
    upload_id = created["upload_id"]

    replay = client.post(f"{BASE}/uploads", json=payload, headers=bearer(owner))
    assert replay.status_code == 200
    check_schema("UploadStatus", replay.json())
    assert replay.json()["upload_id"] == upload_id

    # 同一时刻用不同偏移写法：规范化成 UTC 后视为同一声明
    shifted = declaration(sample_id, {**image, "captured_at": "2026-10-20T01:12:33Z"})
    assert client.post(f"{BASE}/uploads", json=shifted, headers=bearer(owner)).status_code == 200

    # captured_at 参与内容比较：换个采集时间就是异内容
    retimed = declaration(sample_id, {**image, "captured_at": "2026-10-20T09:13:40+08:00"})
    conflict = client.post(f"{BASE}/uploads", json=retimed, headers=bearer(owner))
    assert conflict.status_code == 409
    check_schema("ErrorResponse", conflict.json())
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    changed = declaration(sample_id, image, symptoms="换了症状")
    assert client.post(f"{BASE}/uploads", json=changed, headers=bearer(owner)).status_code == 409

    # 同一 sample_id 被另一 owner 占用：403，且不泄露图片信息
    foreign = client.post(f"{BASE}/uploads", json=payload, headers=bearer(other))
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "FORBIDDEN"
    assert image["image_id"] not in foreign.text
    assert str(upload_id) not in foreign.text

    # 其他 owner 的会话一律 404
    assert client.get(f"{BASE}/uploads/{upload_id}", headers=bearer(other)).status_code == 404
    assert put_image(client, other, upload_id, image, data).status_code == 404
    assert client.post(f"{BASE}/uploads/{upload_id}/complete", headers=bearer(other)).status_code == 404

    # 管理员不读上传会话，也不能代采集；媒体权限另行允许（见上面的媒体断言）
    admin = login(client, "admin")
    assert client.get(f"{BASE}/uploads/{upload_id}", headers=bearer(admin)).status_code == 403
    admin_declare = client.post(
        f"{BASE}/uploads",
        json=declaration(new_uuid7(), image_decl(new_uuid7(), data, "image/png", 8, 6)),
        headers=bearer(admin),
    )
    assert admin_declare.status_code == 403
    assert admin_declare.json()["error"]["code"] == "FORBIDDEN"

    # expert 不能声明
    expert = login(client, "expert")
    expert_payload = declaration(new_uuid7(), image_decl(new_uuid7(), data, "image/png", 8, 6))
    denied = client.post(f"{BASE}/uploads", json=expert_payload, headers=bearer(expert))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


# ---------------- 校验与冲突 ----------------

def test_upload_validation_rules(client: TestClient):
    owner = login(client, "collector1")
    png = png_bytes()
    declared_png = png_with_comment("A" * 16)

    image = image_decl(new_uuid7(), declared_png, "image/png", 8, 6)
    sample_id = new_uuid7()
    upload_id = declare(client, owner, declaration(sample_id, image))["upload_id"]

    # 实际字节与声明等长但 SHA 不同：409，且不标 received
    tampered = png_with_comment("B" * 16)
    assert len(tampered) == len(declared_png)
    mismatch = put_image(client, owner, upload_id, image, tampered)
    assert mismatch.status_code == 409
    check_schema("ErrorResponse", mismatch.json())
    assert mismatch.json()["error"]["code"] == "FILE_MISMATCH"
    assert mismatch.json()["error"]["details"]["reason"] == "sha256_body"
    broken = status_of(client, owner, upload_id)
    assert broken["received_images"] == []
    assert broken["invalid_images"] == [image["image_id"]]
    assert broken["missing_images"] == []

    # 缺失必需头（只给 Content-Type，缺 X-Content-SHA256）
    missing_headers = client.put(
        f"{BASE}/uploads/{upload_id}/images/{image['image_id']}",
        content=png,
        headers={**bearer(owner), "Content-Type": "image/png"},
    )
    assert missing_headers.status_code == 422
    assert missing_headers.json()["error"]["code"] == "VALIDATION_FAILED"

    # 不支持的 MIME
    unsupported = put_image(client, owner, upload_id, image, png, content_type="image/gif")
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_MEDIA"

    # 声明尺寸与实际解码尺寸不符
    wrong_dim = image_decl(new_uuid7(), png, "image/png", 9, 6)
    upload2 = declare(client, owner, declaration(new_uuid7(), wrong_dim))["upload_id"]
    dim_resp = put_image(client, owner, upload2, wrong_dim, png)
    assert dim_resp.status_code == 409
    assert dim_resp.json()["error"]["details"]["reason"] == "dimensions"

    # 声明长度与实际字节数不符（独立 image_id，避免触发全局唯一性；Content-Length 由客户端按真实长度发送）
    short = {**image, "image_id": new_uuid7(), "file_size": len(declared_png) + 5}
    upload3 = declare(client, owner, declaration(new_uuid7(), short))["upload_id"]
    short_resp = put_image(client, owner, upload3, short, declared_png)
    assert short_resp.status_code == 409
    assert short_resp.json()["error"]["details"]["reason"] == "content_length"

    # 声明层校验：重复 image_id、未知字段、无时区时间、无效字典、超大声明体
    duplicate = declaration(new_uuid7(), image, {**image, "view_type": "context"})
    dup_resp = client.post(f"{BASE}/uploads", json=duplicate, headers=bearer(owner))
    assert dup_resp.status_code == 422
    check_schema("ErrorResponse", dup_resp.json())

    unknown_field = declaration(new_uuid7(), image, orchard_id="O-1")
    assert client.post(f"{BASE}/uploads", json=unknown_field, headers=bearer(owner)).status_code == 422

    # device_model 契约上是 required 但可 null：整字段缺失应 422
    missing_model = declaration(new_uuid7(), {k: v for k, v in image.items() if k != "device_model"})
    missing_model_resp = client.post(f"{BASE}/uploads", json=missing_model, headers=bearer(owner))
    assert missing_model_resp.status_code == 422
    assert "device_model" in missing_model_resp.text

    naive_time = declaration(new_uuid7(), {**image, "captured_at": "2026-10-20T09:12:33"})
    naive_resp = client.post(f"{BASE}/uploads", json=naive_time, headers=bearer(owner))
    assert naive_resp.status_code == 422
    assert "captured_at" in naive_resp.text

    bad_dict = declaration(new_uuid7(), image, cultivar_id="not_a_cultivar")
    bad_dict_resp = client.post(f"{BASE}/uploads", json=bad_dict, headers=bearer(owner))
    assert bad_dict_resp.status_code == 422
    assert bad_dict_resp.json()["error"]["details"]["fields"][0]["field"] == "cultivar_id"

    oversized = declaration(new_uuid7(), image, pad="x" * 70000)
    oversized_resp = client.post(f"{BASE}/uploads", json=oversized, headers=bearer(owner))
    assert oversized_resp.status_code == 413
    assert oversized_resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    # image_id 全局唯一：另一个 sample 复用已声明图片
    reused = declaration(new_uuid7(), {**image, "image_id": image["image_id"], "sha256": hashlib.sha256(png).hexdigest()})
    reused_resp = client.post(f"{BASE}/uploads", json=reused, headers=bearer(owner))
    assert reused_resp.status_code == 409
    assert reused_resp.json()["error"]["code"] == "STATE_CONFLICT"

    # 媒体：不存在的图片、非法 variant/w（用一份已接收的图验证参数校验）
    ok_image = image_decl(new_uuid7(), png, "image/png", 8, 6)
    ok_upload = declare(client, owner, declaration(new_uuid7(), ok_image))["upload_id"]
    assert put_image(client, owner, ok_upload, ok_image, png).status_code == 201
    ok_url = f"{BASE}/media/sample-images/{ok_image['image_id']}"
    assert client.get(f"{BASE}/media/sample-images/{new_uuid7()}", headers=bearer(owner)).status_code == 404
    assert client.get(f"{ok_url}?variant=thumb", headers=bearer(owner)).status_code == 422
    assert client.get(f"{ok_url}?variant=preview&w=800", headers=bearer(owner)).status_code == 422
    assert client.get(f"{ok_url}?variant=preview&w=320", headers=bearer(owner)).status_code == 200
