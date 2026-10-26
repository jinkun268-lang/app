"""样本审核 → 导出 闭环测试（TestClient + 进程内状态）。

覆盖：真实两图上传 → 审核 unknown 修正为 citrus_canker → A 图 usable / B 图 unusable
→ 列表与详情按契约 Schema 校验（含筛选与分页参数）→ 旧版本 409 且不覆写 → 导出批次（ExportJob Schema）
→ ZIP 只含 A 图与两张 CSV、标签/原图哈希/包哈希相符 → 同键重放与异内容冲突
→ 创建后改审核仍下载原快照 → collector 写操作 403 / expert 核验与训练权限分离 → 缺少幂等键 422
→ 生成失败保留错误且不出半包，同快照 retry 成功。

测试只通过 HTTP 接口驱动；每个测试使用 create_app() 新建的独立 store，
不依赖其他测试文件或运行顺序。为模拟“原图字节缺失导致导出失败”，
最后一个测试通过文件接口临时移除原图，验证失败与原快照重试。
"""
from __future__ import annotations

import csv
import hashlib
import io
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.app.common import new_uuid7
from server.app.main import create_app
from test_uploads import (
    BASE,
    bearer,
    check_schema,
    declaration,
    declare,
    image_decl,
    jpeg_bytes,
    login,
    png_bytes,
    put_image,
)


# ---------------- 夹具（每个测试一份独立 store，不依赖其他文件或运行顺序） ----------------

@pytest.fixture()
def app():
    # 显式内存存储：测试之间完全隔离，不读写本地数据库文件。
    return create_app("memory")


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


# ---------------- 工具 ----------------

def upload_two_images(client: TestClient) -> dict[str, Any]:
    """真实走四步上传，返回样本与两张图的信息（collector1 为 owner）。"""
    owner = login(client, "collector1")
    png, jpg = png_bytes(8, 6), jpeg_bytes(10, 7)
    image_a = image_decl(new_uuid7(), png, "image/png", 8, 6)
    image_b = image_decl(new_uuid7(), jpg, "image/jpeg", 10, 7)
    sample_id = new_uuid7()

    created = declare(client, owner, declaration(sample_id, image_a, image_b))
    upload_id = created["upload_id"]
    assert put_image(client, owner, upload_id, image_a, png).status_code == 201
    assert put_image(client, owner, upload_id, image_b, jpg).status_code == 201
    done = client.post(f"{BASE}/uploads/{upload_id}/complete", headers=bearer(owner))
    assert done.status_code == 200, done.text
    return {
        "owner": owner,
        "sample_id": sample_id,
        "upload_id": upload_id,
        "a": image_a,
        "b": image_b,
        "png": png,
        "jpg": jpg,
    }


def review_and_qualify(client: TestClient, admin: str, info: dict[str, Any]) -> None:
    """审核修正 + A 图可用 / B 图不可用，逐步按契约校验。"""
    sample_id = info["sample_id"]
    reviewed = client.patch(
        f"{BASE}/samples/{sample_id}/review",
        json={
            "expected_version": 0,
            "review_status": "corrected",
            "final_cultivar_id": "huyou",
            "final_part": "leaf",
            "final_class_id": "citrus_canker",
            "review_note": "原类别不确定，按溃疡病修正",
        },
        headers=bearer(login(client, "expert")),
    )
    assert reviewed.status_code == 200, reviewed.text
    check_schema("SampleDetail", reviewed.json())
    assert reviewed.json()["review_version"] == 1
    assert reviewed.json()["review_status"] == "corrected"
    assert reviewed.json()["final_class_id"] == "citrus_canker"
    assert reviewed.json()["final_class_name"] == "溃疡病"
    # 采集原值保留
    assert reviewed.json()["original_class_id"] == "unknown"
    assert reviewed.json()["original_class_name"] == "不确定"
    assert reviewed.json()["review_events"][0]["action"] == "review"

    quality_a = client.patch(
        f"{BASE}/samples/{sample_id}/images/{info['a']['image_id']}/quality",
        json={"expected_version": 0, "quality_status": "usable", "quality_reason_code": None, "quality_note": None},
        headers=bearer(admin),
    )
    assert quality_a.status_code == 200, quality_a.text
    check_schema("SampleImage", quality_a.json())
    assert quality_a.json()["quality_status"] == "usable"
    assert quality_a.json()["quality_version"] == 1
    assert quality_a.json()["quality_events"][0]["after_status"] == "usable"

    quality_b = client.patch(
        f"{BASE}/samples/{sample_id}/images/{info['b']['image_id']}/quality",
        json={"expected_version": 0, "quality_status": "unusable", "quality_reason_code": "blur"},
        headers=bearer(admin),
    )
    assert quality_b.status_code == 200, quality_b.text
    check_schema("SampleImage", quality_b.json())
    assert quality_b.json()["quality_status"] == "unusable"
    assert quality_b.json()["quality_reason_code"] == "blur"


def wait_export(client: TestClient, admin: str, export_id: str, timeout: float = 3.0) -> dict[str, Any]:
    """轮询批次状态；后台生成在内存里完成，通常在首个 GET 前就已结束。"""
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        resp = client.get(f"{BASE}/exports/{export_id}", headers=bearer(admin))
        assert resp.status_code == 200, resp.text
        last = resp.json()
        check_schema("ExportJob", last)
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.02)
    raise AssertionError(f"导出未在 {timeout}s 内结束：{last}")


def read_csv(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8")
    assert not text.startswith("\ufeff"), "CSV 不得带 BOM"
    assert "\r\n" not in text, "CSV 必须是 LF 换行"
    return list(csv.reader(text.splitlines()))


# ---------------- 主闭环 ----------------

@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_withdrawal_hides_samples_and_new_exports_but_preserves_history(tmp_path, backend):
    url = "memory" if backend == "memory" else f"sqlite+pysqlite:///{(tmp_path / 'withdraw.sqlite3').as_posix()}"
    with TestClient(create_app(url, storage_root=tmp_path / "files")) as test_client:
        info = upload_two_images(test_client)
        admin = login(test_client, "admin")
        expert = login(test_client, "expert")
        other = login(test_client, "collector2")
        sample_id = info["sample_id"]
        review_and_qualify(test_client, admin, info)
        before = test_client.post(f"{BASE}/exports", json={"format": "dataset"},
            headers={**bearer(admin), "Idempotency-Key": new_uuid7()})
        assert before.status_code == 202, before.text
        export = wait_export(test_client, admin, before.json()["export_id"])
        assert export["item_count"] == 1
        endpoint = f"{BASE}/samples/{sample_id}/withdraw"
        assert test_client.post(endpoint, headers=bearer(other)).status_code == 404
        assert test_client.post(endpoint, headers=bearer(admin)).status_code == 403
        first = test_client.post(endpoint, headers=bearer(info["owner"]))
        assert first.status_code == 200, first.text
        assert test_client.post(endpoint, headers=bearer(info["owner"])).json() == first.json()
        assert test_client.get(f"{BASE}/samples", headers=bearer(admin)).json()["total"] == 0
        assert test_client.get(f"{BASE}/samples/{sample_id}", headers=bearer(admin)).status_code == 404
        assert test_client.get(f"{BASE}/media/sample-images/{info['a']['image_id']}", headers=bearer(admin)).status_code == 404
        assert test_client.post(f"{BASE}/uploads/{info['upload_id']}/complete", headers=bearer(info["owner"])).status_code == 409
        assert test_client.patch(f"{BASE}/samples/{sample_id}/review", json={"expected_version": 2, "review_status": "confirmed"}, headers=bearer(expert)).status_code == 409
        after = test_client.post(f"{BASE}/exports", json={"format": "dataset"},
            headers={**bearer(admin), "Idempotency-Key": new_uuid7()})
        assert after.status_code == 202, after.text
        assert wait_export(test_client, admin, after.json()["export_id"])["item_count"] == 0
        assert test_client.get(f"{BASE}/exports/{export['export_id']}/download", headers=bearer(admin)).status_code == 200


def test_review_then_export_only_usable_image(client: TestClient):
    info = upload_two_images(client)
    admin = login(client, "admin")
    sample_id, sample_a, sample_b = info["sample_id"], info["a"]["image_id"], info["b"]["image_id"]

    review_and_qualify(client, admin, info)

    # 列表：默认只列 complete 样本，字段符合 SampleSummaryPage
    listing = client.get(f"{BASE}/samples", headers=bearer(admin))
    assert listing.status_code == 200, listing.text
    check_schema("SampleSummaryPage", listing.json())
    assert listing.json()["total"] == 1
    summary = listing.json()["items"][0]
    assert summary["sample_id"] == sample_id
    assert summary["image_count"] == 2
    assert summary["first_image_id"] == sample_a
    assert summary["review_status"] == "corrected"
    assert summary["final_class_id"] == "citrus_canker"
    assert summary["excluded"] is False

    # 筛选与分页：q 精确 sample_id / tree_id 前缀，review_status 多值，北京时间整日
    def total_of(params: dict[str, Any]) -> int:
        resp = client.get(f"{BASE}/samples", params=params, headers=bearer(admin))
        assert resp.status_code == 200, resp.text
        check_schema("SampleSummaryPage", resp.json())
        return resp.json()["total"]

    assert total_of({"q": sample_id}) == 1
    assert total_of({"q": "T-00"}) == 1
    assert total_of({"q": "T-99"}) == 0
    assert total_of({"review_status": "corrected"}) == 1
    assert total_of({"review_status": "unresolved,confirmed"}) == 0
    assert total_of({"excluded": False}) == 1
    assert total_of({"final_class_id": "citrus_canker"}) == 1
    today = datetime.now(timezone(timedelta(hours=8))).date()
    assert total_of({"uploaded_from": today.isoformat()}) == 1
    assert total_of({"uploaded_to": (today - timedelta(days=1)).isoformat()}) == 0
    for bad in (
        {"page": 0},
        {"page_size": 101},
        {"review_status": "bogus"},
        {"uploaded_from": "2026-13-01"},
        {"upload_state": "receiving"},
    ):
        resp = client.get(f"{BASE}/samples", params=bad, headers=bearer(admin))
        assert resp.status_code == 422, (bad, resp.text)
        check_schema("ErrorResponse", resp.json())
        assert resp.json()["error"]["code"] == "VALIDATION_FAILED"

    # 详情：投影不含内部字段
    detail_resp = client.get(f"{BASE}/samples/{sample_id}", headers=bearer(admin))
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    check_schema("SampleDetail", detail)
    assert detail["upload_state"] == "complete"
    assert "owner_id" not in detail and "upload_id" not in detail
    for image in detail["images"]:
        assert "sha256" not in image and "receive_status" not in image
    assert {image["image_id"] for image in detail["images"]} == {sample_a, sample_b}

    # 旧版本提交 409 且不覆写既有审核
    stale = client.patch(
        f"{BASE}/samples/{sample_id}/review",
        json={"expected_version": 0, "review_status": "unresolved"},
        headers=bearer(login(client, "expert")),
    )
    assert stale.status_code == 409, stale.text
    check_schema("ErrorResponse", stale.json())
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert stale.json()["error"]["details"]["current_version"] == 1
    unchanged = client.get(f"{BASE}/samples/{sample_id}", headers=bearer(admin)).json()
    assert unchanged["review_version"] == 1
    assert unchanged["review_status"] == "corrected"
    assert unchanged["final_class_id"] == "citrus_canker"
    assert unchanged["review_note"] == "原类别不确定，按溃疡病修正"

    # 创建导出：202 + 完整 ExportJob
    key = new_uuid7()
    created = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(admin), "Idempotency-Key": key},
    )
    assert created.status_code == 202, created.text
    job = created.json()
    check_schema("ExportJob", job)
    assert job["status"] == "queued"
    assert job["item_count"] == 1
    assert job["filters"]["format"] == "dataset"
    export_id = job["export_id"]

    finished = wait_export(client, admin, export_id)
    assert finished["status"] == "succeeded"
    assert finished["item_count"] == 1
    assert finished["zip_sha256"] and finished["zip_size"]
    assert finished["error_code"] is None

    # 同键同内容重放：同一 export_id
    replay = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(admin), "Idempotency-Key": key},
    )
    assert replay.status_code == 202
    assert replay.json()["export_id"] == export_id

    # 同键异内容：409 IDEMPOTENCY_CONFLICT
    conflict = client.post(
        f"{BASE}/exports",
        json={"format": "dataset", "final_class_id": "citrus_canker"},
        headers={**bearer(admin), "Idempotency-Key": key},
    )
    assert conflict.status_code == 409, conflict.text
    check_schema("ErrorResponse", conflict.json())
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # 幂等按用户隔离：同一键换账号是另一次创建，不是冲突
    super_token = login(client, "super")
    other = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(super_token), "Idempotency-Key": key},
    )
    assert other.status_code == 202, other.text
    assert other.json()["export_id"] != export_id

    # 批次列表
    page = client.get(f"{BASE}/exports", headers=bearer(admin))
    assert page.status_code == 200, page.text
    check_schema("ExportJobPage", page.json())
    assert page.json()["total"] >= 1
    assert export_id in {item["export_id"] for item in page.json()["items"]}

    # 下载：application/zip + 固定文件名 + 哈希/大小与批次一致
    download = client.get(f"{BASE}/exports/{export_id}/download", headers=bearer(admin))
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/zip"
    assert f'dataset-{export_id}.zip' in download.headers["content-disposition"]
    assert len(download.content) == finished["zip_size"]
    assert hashlib.sha256(download.content).hexdigest() == finished["zip_sha256"]

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        # 只含 A 图（B 图不可用不入包）与两张 CSV，顺序稳定
        assert names == [f"images/{sample_a}.png", "labels.csv", "classes.csv"]
        assert sample_b not in " ".join(names)
        # 原图字节未重编码
        assert archive.read(f"images/{sample_a}.png") == info["png"]
        assert archive.getinfo(f"images/{sample_a}.png").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("labels.csv").compress_type == zipfile.ZIP_DEFLATED

        labels = read_csv(archive.read("labels.csv"))
        assert labels[0] == ["image_id", "sample_id", "file_name", "class_id"]
        assert labels[1] == [sample_a, sample_id, f"{sample_a}.png", "citrus_canker"]
        assert len(labels) == 2

        classes = read_csv(archive.read("classes.csv"))
        assert classes[0] == ["class_id", "class_name"]
        assert classes[1] == ["citrus_canker", "溃疡病"]
        assert len(classes) == 2

        # 条目时间固定为快照时间（ZIP 的 DOS 时间精度 2 秒），重试重生成的字节稳定
        snapshot = datetime.fromisoformat(finished["snapshot_at"].replace("Z", "+00:00"))
        expected_stamp = (
            snapshot.year, snapshot.month, snapshot.day,
            snapshot.hour, snapshot.minute, (snapshot.second // 2) * 2,
        )
        for name in names:
            assert archive.getinfo(name).date_time == expected_stamp

    # 创建后改审核：原快照与下载字节不变
    changed = client.patch(
        f"{BASE}/samples/{sample_id}/review",
        json={"expected_version": 1, "review_status": "unresolved", "review_note": "证据不足，改为无法判断"},
        headers=bearer(login(client, "expert")),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["review_version"] == 2
    assert changed.json()["review_status"] == "unresolved"
    assert changed.json()["final_class_id"] is None
    assert changed.json()["final_cultivar_id"] is None

    again = client.get(f"{BASE}/exports/{export_id}/download", headers=bearer(admin))
    assert again.status_code == 200
    assert again.content == download.content
    assert client.get(f"{BASE}/exports/{export_id}", headers=bearer(admin)).json()["zip_sha256"] == finished["zip_sha256"]

    # 改审核后新建的批次不再包含该样本：空结果仍生成只有表头的合法 ZIP
    empty_job = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(admin), "Idempotency-Key": new_uuid7()},
    )
    assert empty_job.status_code == 202
    assert empty_job.json()["item_count"] == 0
    empty_done = wait_export(client, admin, empty_job.json()["export_id"])
    assert empty_done["status"] == "succeeded"
    empty_zip = client.get(f"{BASE}/exports/{empty_done['export_id']}/download", headers=bearer(admin))
    assert empty_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(empty_zip.content)) as archive:
        assert archive.namelist() == ["labels.csv", "classes.csv"]
        assert read_csv(archive.read("labels.csv")) == [["image_id", "sample_id", "file_name", "class_id"]]
        assert read_csv(archive.read("classes.csv")) == [["class_id", "class_name"]]

    # 不存在的批次下载 → 404
    assert client.get(f"{BASE}/exports/{new_uuid7()}/download", headers=bearer(admin)).status_code == 404


# ---------------- 权限与幂等键 ----------------

def test_permissions_and_idempotency_key(client: TestClient):
    info = upload_two_images(client)
    admin = login(client, "admin")
    sample_id, image_id = info["sample_id"], info["a"]["image_id"]
    collector = login(client, "collector1")
    other_collector = login(client, "collector2")
    expert = login(client, "expert")

    review_url = f"{BASE}/samples/{sample_id}/review"
    quality_url = f"{BASE}/samples/{sample_id}/images/{image_id}/quality"

    # collector 可读本人详情，但看不到别人的样本
    assert client.get(f"{BASE}/samples/{sample_id}", headers=bearer(collector)).status_code == 200
    assert client.get(f"{BASE}/samples/{sample_id}", headers=bearer(other_collector)).status_code == 404
    # collector 列表仅包含本人数据
    assert client.get(f"{BASE}/samples", headers=bearer(collector)).json()["total"] == 1
    assert client.get(f"{BASE}/samples", headers=bearer(other_collector)).json()["total"] == 0
    # expert 可读样本并核验，不能进行训练操作
    assert client.get(f"{BASE}/samples/{sample_id}", headers=bearer(expert)).status_code == 200
    assert client.get(f"{BASE}/samples", headers=bearer(expert)).status_code == 200

    assert client.patch(review_url, json={"expected_version": 0, "review_status": "unresolved"}, headers=bearer(admin)).status_code == 403
    assert client.patch(quality_url, json={"expected_version": 0, "quality_status": "usable"}, headers=bearer(expert)).status_code == 403
    assert client.patch(quality_url, json={"expected_version": 0, "quality_status": "usable"}, headers=bearer(admin)).status_code == 409
    assert client.post(f"{BASE}/samples/{sample_id}/exclude", json={"expected_version": 0}, headers=bearer(expert)).status_code == 403

    # collector 不能写审核/质量/排除（403，且不改数据）
    write_headers = bearer(collector)
    for resp in (
        client.patch(review_url, json={
            "expected_version": 0,
            "review_status": "corrected",
            "final_cultivar_id": "huyou",
            "final_part": "leaf",
            "final_class_id": "citrus_canker",
        }, headers=write_headers),
        client.patch(quality_url, json={"expected_version": 0, "quality_status": "usable"}, headers=write_headers),
        client.post(f"{BASE}/samples/{sample_id}/exclude", json={"expected_version": 0}, headers=write_headers),
        client.post(f"{BASE}/samples/{sample_id}/restore", json={"expected_version": 0}, headers=write_headers),
    ):
        assert resp.status_code == 403, resp.text
        check_schema("ErrorResponse", resp.json())
        assert resp.json()["error"]["code"] == "FORBIDDEN"
    untouched = client.get(f"{BASE}/samples/{sample_id}", headers=bearer(admin)).json()
    assert untouched["review_version"] == 0
    assert untouched["review_status"] == "unreviewed"

    # 非管理角色不能创建/查看/下载导出
    export_body = {"format": "dataset"}
    assert client.post(
        f"{BASE}/exports", json=export_body,
        headers={**bearer(collector), "Idempotency-Key": new_uuid7()},
    ).status_code == 403
    assert client.get(f"{BASE}/exports", headers=bearer(expert)).status_code == 403

    # 缺少 Idempotency-Key：422 VALIDATION_FAILED
    missing = client.post(f"{BASE}/exports", json=export_body, headers=bearer(admin))
    assert missing.status_code == 422, missing.text
    check_schema("ErrorResponse", missing.json())
    assert missing.json()["error"]["code"] == "VALIDATION_FAILED"

    # 非法审核请求：unresolved 带 final_* 字段 / expected_version 为 bool / 未审核状态
    unresolved_with_final = client.patch(
        review_url,
        json={"expected_version": 0, "review_status": "unresolved", "final_class_id": None},
        headers=bearer(expert),
    )
    assert unresolved_with_final.status_code == 422, unresolved_with_final.text
    assert unresolved_with_final.json()["error"]["code"] == "VALIDATION_FAILED"

    bool_version = client.patch(
        review_url,
        json={"expected_version": True, "review_status": "unresolved"},
        headers=bearer(expert),
    )
    assert bool_version.status_code == 422, bool_version.text

    unreviewed = client.patch(
        review_url,
        json={"expected_version": 0, "review_status": "unreviewed"},
        headers=bearer(expert),
    )
    assert unreviewed.status_code == 422, unreviewed.text

    review_and_qualify(client, admin, info)
    # 通过核验后，不可用图必须给有效原因
    bad_reason = client.patch(
        quality_url,
        json={"expected_version": 1, "quality_status": "unusable", "quality_reason_code": "not_a_reason"},
        headers=bearer(admin),
    )
    assert bad_reason.status_code == 422, bad_reason.text

    # 排除后不再进入导出：qualified → 排除 → item_count=0
    excluded = client.post(
        f"{BASE}/samples/{sample_id}/exclude",
        json={"expected_version": 1, "reason": "测试排除"},
        headers=bearer(admin),
    )
    assert excluded.status_code == 200, excluded.text
    check_schema("SampleDetail", excluded.json())
    assert excluded.json()["excluded"] is True
    assert excluded.json()["review_version"] == 2
    assert excluded.json()["review_events"][0]["action"] == "exclude"

    job = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(admin), "Idempotency-Key": new_uuid7()},
    )
    assert job.status_code == 202
    assert job.json()["item_count"] == 0

    restored = client.post(
        f"{BASE}/samples/{sample_id}/restore",
        json={"expected_version": 2, "reason": None},
        headers=bearer(admin),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["excluded"] is False
    assert restored.json()["review_version"] == 3


# ---------------- 失败与重试 ----------------

def test_export_failure_keeps_error_and_retry_uses_same_snapshot(client: TestClient):
    info = upload_two_images(client)
    admin = login(client, "admin")
    sample_a = info["a"]["image_id"]
    review_and_qualify(client, admin, info)

    store = client.app.state.store
    # 模拟原图字节丢失：快照仍能创建，但生成时必须失败且不产出半包。
    files = client.app.state.files
    file_key = store.samples[info["sample_id"]]["images"][0]["file_key"]
    with files.open_read(file_key) as source:
        missing_bytes = source.read()
    files.delete(file_key)

    created = client.post(
        f"{BASE}/exports",
        json={"format": "dataset"},
        headers={**bearer(admin), "Idempotency-Key": new_uuid7()},
    )
    assert created.status_code == 202, created.text
    export_id = created.json()["export_id"]
    assert created.json()["item_count"] == 1

    failed = wait_export(client, admin, export_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "FILE_MISMATCH"
    assert failed["error_detail"]
    assert failed["zip_sha256"] is None and failed["zip_size"] is None

    refused = client.get(f"{BASE}/exports/{export_id}/download", headers=bearer(admin))
    assert refused.status_code == 409, refused.text
    check_schema("ErrorResponse", refused.json())
    assert refused.json()["error"]["code"] == "STATE_CONFLICT"

    # 原图恢复后按原快照重试：同 export_id、同 item_count、不重新选样
    files.write(file_key, missing_bytes)
    retried = client.post(
        f"{BASE}/exports/{export_id}/retry",
        headers={**bearer(admin), "Idempotency-Key": new_uuid7()},
    )
    assert retried.status_code == 202, retried.text
    check_schema("ExportJob", retried.json())
    assert retried.json()["export_id"] == export_id
    assert retried.json()["status"] == "queued"
    assert retried.json()["item_count"] == 1

    ok = wait_export(client, admin, export_id)
    assert ok["status"] == "succeeded"
    assert ok["error_code"] is None
    assert ok["zip_sha256"] and ok["zip_size"]

    download = client.get(f"{BASE}/exports/{export_id}/download", headers=bearer(admin))
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == ok["zip_sha256"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read(f"images/{sample_a}.png") == info["png"]
        labels = read_csv(archive.read("labels.csv"))
        assert labels[1][0] == sample_a
        assert labels[1][3] == "citrus_canker"

    # 成功的批次不能再重试
    again = client.post(
        f"{BASE}/exports/{export_id}/retry",
        headers={**bearer(admin), "Idempotency-Key": new_uuid7()},
    )
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "STATE_CONFLICT"
