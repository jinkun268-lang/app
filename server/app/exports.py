"""数据导出：创建冻结快照、磁盘 ZIP 生成、列表/详情/重试/流式下载。

存储边界（元数据与二进制分离）：
- 元数据（导出任务、冻结条目、幂等记录）只经 `storage.transaction()` 读写；一次短事务内完成
  "读取/版本判断/写入/追加历史"，不跨请求或跨生成过程持有事务。
- 图片与 ZIP 字节只经 `app.state.files` 的 `FileStorage`（`open_read` / `stage` / staged `publish` / `delete`）；元数据只保留 `file_key` / `zip_key` 这类相对键与哈希、大小，
  不出现图片或 ZIP 字节（storage 层遇到 bytes 会直接报错）。

业务流程：
- 创建：一个事务里冻结样本/图片 ID、类别标签名、文件名、原图 `file_key`、SHA、筛选条件与
  taxonomy 版本，同时写入任务与幂等记录；提交后有界执行器生成，202 返回完整 `ExportJob`。
- 幂等：作用域 = 操作 + 用户 + 原始 `Idempotency-Key`，规范编码后取 sha256 作为固定 64 位小写
  十六进制槽位，既保持作用域语义，也避免超长记录键在 MySQL 上失败、以及大小写无关排序规则的歧义。
  请求摘要沿用原规则；跨重启同键同内容复用原任务，异内容 409 `IDEMPOTENCY_CONFLICT`。
- 生成：`_run_export(storage, files, export_id)` 先在一个短事务里 queued→running 并取出冻结清单，
  释放事务后写到 `files.stage()` 提供的受控暂存流；原图按 `file_key` 流式分块拷入
  `archive.open(ZipInfo, "w")`，不把整包或全部原图读进内存。原图上传时已校验且不可变，
  这里默认不再逐张重算 SHA；缺文件/读失败整批 failed，不发布半包。
  完成后对已发布 ZIP 流式计算一次 sha256 与大小，再用另一个事务提交 succeeded 与 zip_key/size/sha。
- 重试：保持同 `export_id`、同 frozen items/filters/snapshot_at、同幂等语义；只有 failed 允许重试，
  读取接口不推进任务。
- 下载：`files.open_read` 交给流式响应，及时关闭句柄，不整包入内存；鉴权/文件名/错误格式不变。
- 重启恢复：`recover_interrupted(storage)` 在启动时把残留 queued/running 置 failed
  （`INTERNAL`，可按原快照重试），保留冻结条目与幂等记录。首版部署约定单个 API 进程/单个
  导出执行者，不引入 Redis/Celery 或多 worker 选主；存储、文件接口本身仍可替换实现。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from typing import Any, BinaryIO, Iterator, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from .common import DomainError, iso_utc, new_uuid7, require_roles
from .data_access import DataTransaction, FileStorage, MetadataStorage, SampleFilter, StorageUnavailable
from .review import beijing_day_bound, parse_utc
from .resources import ServiceLimits

router = APIRouter(prefix="/api/v1")

_ADMIN_ROLES = ("admin", "super_admin")

_EXT_BY_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_ELIGIBLE_REVIEW_STATUSES = ("confirmed", "corrected")
_SORT_FLOOR = datetime.min.replace(tzinfo=timezone.utc)
# ZIP 的 date_time 最小编码是 1980-01-01；只在快照时间无法解析时兜底使用。
_ZIP_FLOOR = datetime(1980, 1, 1, tzinfo=timezone.utc)

# 生成/下载的流式块大小：避免整包或整图入内存。
CHUNK_SIZE = 1024 * 1024

ZIP_NAME_PREFIX = "dataset-"
INTERRUPTED_DETAIL = "服务中断，导出未完成；可按原快照重试"


# ---------------- 请求 DTO ----------------

class ExportCreateIn(BaseModel):
    """创建导出批次；无果园字段，未知字段拒绝。"""

    model_config = ConfigDict(extra="forbid")

    format: Literal["dataset"]
    uploaded_from: date | None = None
    uploaded_to: date | None = None
    final_cultivar_id: str | None = None
    final_class_id: str | None = None


# ---------------- 幂等 ----------------

def _idempotency_slot(user: dict[str, Any], operation: str, key: str) -> str:
    """幂等槽：操作 + 用户 + 原始键的规范编码再散列，固定 64 位小写十六进制。

    直接拼接最长可达 190 字符，超过元数据记录键长度 128（MySQL 会失败）；
    散列后长度固定，且大小写无关的排序规则下也不会把不同键当作同一个。
    """
    canonical = json.dumps([operation, str(user["user_id"]), key], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_hash(payload: BaseModel) -> str:
    blob = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _idempotency_key_header(value: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)) -> str:
    return value


def _zip_key(export_id: str) -> str:
    """ZIP 相对键：同一批次始终写同一个键，重试不会产生第二份产物。"""
    return f"exports/{export_id}.zip"


# ---------------- 资格与快照 ----------------

def _class_name(store: DataTransaction, class_id: str | None) -> str | None:
    if class_id is None:
        return None
    row = store.get_class(class_id)
    return row["name"] if row is not None else class_id


def _eligible_class(store: DataTransaction, class_id: str | None) -> bool:
    """最终类别可用于导出：非 unknown、非 tmp_ 临时占位、字典存在且非 provisional。"""
    if not class_id or class_id == "unknown" or class_id.startswith("tmp_"):
        return False
    row = store.get_class(class_id)
    return row is not None and not bool(row.get("is_provisional", False))


def _export_too_large(limits):
    return DomainError(413, 'PAYLOAD_TOO_LARGE', '导出范围过大，请缩小筛选范围后重试', {
        'max_images': limits.export_max_images, 'max_samples': limits.export_max_images,
        'max_bytes': limits.export_max_bytes})


def _check_retry_budget(store, job, limits):
    if job['item_count'] > limits.export_max_images:
        raise _export_too_large(limits)
    samples = {}
    total = 0
    for item in job['items']:
        sid = item['sample_id']
        if sid not in samples:
            sample = store.get_sample(sid)
            samples[sid] = {image['image_id']: image for image in sample['images']} if sample else {}
        image = samples[sid].get(item['image_id'])
        if image is not None:
            total += image['file_size']
        if total > limits.export_max_bytes:
            raise _export_too_large(limits)


def _replay(store, slot, request_hash, scope):
    existing = store.get_idempotency(slot)
    if existing is None:
        return None
    if existing['request_hash'] != request_hash:
        raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '同一幂等键对应不同请求内容', {'scope': scope})
    job = store.get_export(existing['export_id'])
    if job is None:
        raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '幂等键对应的批次已不存在', {'scope': scope})
    return _job_out(job)


def _snapshot_items(store: DataTransaction, payload: ExportCreateIn, limits: ServiceLimits) -> list[dict[str, Any]]:
    """按导出资格固定条目（含原图 file_key 与 SHA）；结果排序稳定（sample_id, image_id）。"""
    lower = beijing_day_bound(payload.uploaded_from, end=False) if payload.uploaded_from else None
    upper = beijing_day_bound(payload.uploaded_to, end=True) if payload.uploaded_to else None

    items: list[dict[str, Any]] = []
    filters = SampleFilter(
            review_statuses=_ELIGIBLE_REVIEW_STATUSES, excluded=False,
            final_class_id=payload.final_class_id, final_cultivar_id=payload.final_cultivar_id,
            uploaded_from=lower, uploaded_to=upper)
    total_bytes = 0
    page = 1
    while True:
        batch = store.list_samples(filters, page, 100)
        if batch.total > limits.export_max_images:
            raise _export_too_large(limits)
        for sample in batch.items:
            if sample["upload_state"] != "complete":
                continue
            if sample["excluded"]:
                continue
            if sample["review_status"] not in _ELIGIBLE_REVIEW_STATUSES:
                continue
            class_id = sample["final_class_id"]
            if not _eligible_class(store, class_id):
                continue
            if payload.final_class_id is not None and class_id != payload.final_class_id:
                continue
            if payload.final_cultivar_id is not None and sample["final_cultivar_id"] != payload.final_cultivar_id:
                continue
            completed = parse_utc(sample["upload_completed_at"])
            if lower is not None and (completed is None or completed < lower):
                continue
            if upper is not None and (completed is None or completed >= upper):
                continue

            class_name = _class_name(store, class_id)
            for image in sample["images"]:
                if image["receive_status"] != "received":
                    continue
                if image["quality_status"] != "usable":
                    continue
                ext = _EXT_BY_MIME.get(image["mime_type"])
                if ext is None:
                    continue
                total_bytes += image['file_size']
                if len(items) >= limits.export_max_images or total_bytes > limits.export_max_bytes:
                    raise _export_too_large(limits)
                items.append({
                    "image_id": image["image_id"],
                    "sample_id": sample["sample_id"],
                    "file_name": f"{image['image_id']}.{ext}",
                    "class_id": class_id,
                    "class_name": class_name,
                    "collection_metadata": {key: sample.get(key) for key in ("batch_id", "batch_snapshot", "latitude", "longitude", "location_accuracy_m")},
                    # 冻结原图相对键与 SHA：之后上传/审核变化不影响已建批次。
                    "file_key": image.get("file_key"),
                    "sha256": image.get("sha256"),
                })
        if page * 100 >= batch.total:
            break
        page += 1
    items.sort(key=lambda item: (item["sample_id"], item["image_id"]))
    return items


def _job_out(job: dict[str, Any]) -> dict[str, Any]:
    """ExportJob 投影；不暴露 zip_key / 物理路径等实现细节。"""
    return {
        "export_id": job["export_id"],
        "format": job["format"],
        "status": job["status"],
        "filters": dict(job["filters"]),
        "snapshot_at": job["snapshot_at"],
        "taxonomy_version": job["taxonomy_version"],
        "item_count": job["item_count"],
        "zip_sha256": job.get("zip_sha256"),
        "zip_size": job.get("zip_size"),
        "error_code": job.get("error_code"),
        "error_detail": job.get("error_detail"),
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


# ---------------- ZIP 生成 ----------------

class _ExportFailure(Exception):
    """可归因的生成失败：落成 failed 并保留 error_code/error_detail，不发布半包。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    """UTF-8 无 BOM、LF、标准 CSV 转义（含逗号/引号/换行的字段自动加引号并双写引号）。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _zip_entry(name: str, snapshot_at: datetime, compress_type: int) -> zipfile.ZipInfo:
    """条目时间固定为快照时间（ZIP/DOS 时间精度 2 秒），重试生成的文件字节稳定。"""
    info = zipfile.ZipInfo(
        filename=name,
        date_time=(snapshot_at.year, snapshot_at.month, snapshot_at.day,
                   snapshot_at.hour, snapshot_at.minute, (snapshot_at.second // 2) * 2),
    )
    info.compress_type = compress_type
    return info


def _copy_original(archive: zipfile.ZipFile, files: FileStorage, item: dict[str, Any],
                   snapshot_at: datetime, budget: list[int]) -> None:
    """原图按冻结 file_key 流式拷入归档（不重编码、不整图入内存，也不重算 SHA）。"""
    file_key = item.get("file_key")
    if not file_key:
        raise _ExportFailure("FILE_MISMATCH", f"原图文件键缺失：{item['image_id']}")
    entry = _zip_entry(f"images/{item['file_name']}", snapshot_at, zipfile.ZIP_STORED)
    try:
        source = files.open_read(str(file_key))
    except (OSError, StorageUnavailable):
        # 缺文件/打开失败：整批失败，不保留半包。
        raise _ExportFailure("FILE_MISMATCH", f"原图不可读：{item['image_id']}") from None
    try:
        with source, archive.open(entry, "w") as target:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                budget[0] -= len(chunk)
                if budget[0] < 0:
                    raise _ExportFailure('PAYLOAD_TOO_LARGE', '导出图片合计超过大小上限')
                target.write(chunk)
    except OSError:
        raise _ExportFailure("FILE_MISMATCH", f"原图读取或归档写入失败：{item['image_id']}") from None


def _write_zip(archive: zipfile.ZipFile, files: FileStorage, items: list[dict[str, Any]],
               snapshot_at: datetime, max_bytes: int) -> None:
    """条目顺序固定：先按冻结顺序写入图片，再写 labels.csv、classes.csv。"""
    budget = [max_bytes]
    for item in items:
        _copy_original(archive, files, item, snapshot_at, budget)
    labels = _csv_bytes(
        ["image_id", "sample_id", "file_name", "class_id"],
        [[item["image_id"], item["sample_id"], item["file_name"], item["class_id"]] for item in items],
    )
    archive.writestr(_zip_entry("labels.csv", snapshot_at, zipfile.ZIP_DEFLATED), labels)
    metadata_rows = []
    for item in items:
        meta = item.get("collection_metadata") or {}
        batch = meta.get("batch_snapshot") or {}
        metadata_rows.append([item["image_id"], item["sample_id"], meta.get("batch_id") or "",
                              batch.get("name") or "", batch.get("place") or "", batch.get("collector") or "",
                              *("" if meta.get(key) is None else str(meta[key]) for key in ("latitude", "longitude", "location_accuracy_m"))])
    archive.writestr(_zip_entry("collection.csv", snapshot_at, zipfile.ZIP_DEFLATED),
                     _csv_bytes(["image_id", "sample_id", "batch_id", "batch_name", "place", "collector", "latitude", "longitude", "location_accuracy_m"], metadata_rows))
    classes = sorted({(item["class_id"], item["class_name"] or item["class_id"]) for item in items})
    archive.writestr(
        _zip_entry("classes.csv", snapshot_at, zipfile.ZIP_DEFLATED),
        _csv_bytes(["class_id", "class_name"], [[class_id, name] for class_id, name in classes]),
    )


def _stream_digest(files: FileStorage, key: str) -> tuple[str, int]:
    """对已发布 ZIP 流式计算一次 sha256 与字节数（对外字段用，不做多轮校验）。"""
    digest = hashlib.sha256()
    size = 0
    with files.open_read(key) as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _mark_failed(storage: MetadataStorage, export_id: str, code: str, detail: str) -> None:
    with storage.transaction() as store:
        job = store.get_export(export_id)
        if job is None:
            return
        job["status"] = "failed"
        job["error_code"] = code
        job["error_detail"] = detail
        job["finished_at"] = iso_utc()
        job["zip_key"] = None
        job["zip_sha256"] = None
        job["zip_size"] = None


def _run_export(storage: MetadataStorage, files: FileStorage, export_id: str, max_bytes: int = 1024 * 1024 * 1024) -> None:
    """后台生成：短事务 queued→running → 释放事务写磁盘 → 发布 → 短事务提交结果。"""
    with storage.transaction() as store:
        job = store.get_export(export_id)
        if job is None or job.get("status") != "queued":
            return
        job["status"] = "running"
        job["started_at"] = iso_utc()
        items = [dict(item) for item in job.get("items", [])]
        snapshot_at = parse_utc(job.get("snapshot_at")) or _ZIP_FLOOR
        key = _zip_key(export_id)

    try:
        with files.stage() as staged:
            with zipfile.ZipFile(staged.stream, "w", allowZip64=True) as archive:
                _write_zip(archive, files, items, snapshot_at, max_bytes)
            if staged.stream.tell() > max_bytes:
                raise _ExportFailure('PAYLOAD_TOO_LARGE', '生成的ZIP超过大小上限，请缩小筛选范围')
            staged.publish(key)
        zip_sha256, zip_size = _stream_digest(files, key)
    except _ExportFailure as exc:
        _mark_failed(storage, export_id, exc.code, exc.detail)
        return
    except (OSError, StorageUnavailable):
        _mark_failed(storage, export_id, "UNAVAILABLE", "导出文件写入失败，请稍后按原快照重试")
        return
    except Exception:  # noqa: BLE001 - 任何生成异常都落成批次失败，不返回半成品
        _mark_failed(storage, export_id, "INTERNAL", "导出生成失败")
        return
    with storage.transaction() as store:
        job = store.get_export(export_id)
        if job is None:
            return
        job["status"] = "succeeded"
        job["zip_key"] = key
        job["zip_sha256"] = zip_sha256
        job["zip_size"] = zip_size
        job["error_code"] = None
        job["error_detail"] = None
        job["finished_at"] = iso_utc()


def recover_interrupted(storage: MetadataStorage) -> int:
    """启动恢复：把残留 queued/running 置 failed，保留冻结条目与幂等记录。

    首版约定单进程/单导出执行者，因此残留状态一定来自上一次进程中断；
    调用方需在开始接收请求前调用一次（不扫描磁盘、不重新验哈希）。
    """
    now = iso_utc()
    recovered = 0
    with storage.transaction() as store:
        for job in store.interrupted_exports():
            if job.get("status") not in ("queued", "running"):
                continue
            job["status"] = "failed"
            job["error_code"] = "INTERNAL"
            job["error_detail"] = INTERRUPTED_DETAIL
            job["finished_at"] = now
            job["zip_key"] = None
            job["zip_sha256"] = None
            job["zip_size"] = None
            recovered += 1
    return recovered


# ---------------- 接口 ----------------

@router.post("/exports", tags=["exports"], status_code=202, summary="创建导出快照")
def create_export(
    payload: ExportCreateIn,
    request: Request,
    user: dict[str, Any] = Depends(require_roles(*_ADMIN_ROLES)),
    idempotency_key: str = Depends(_idempotency_key_header),
) -> dict[str, Any]:
    storage: MetadataStorage = request.app.state.storage
    files: FileStorage = request.app.state.files
    slot = _idempotency_slot(user, "export.create", idempotency_key)
    request_hash = _request_hash(payload)

    # 一个事务里完成：幂等判定 → 冻结条目 → 写任务 → 写幂等记录。
    with storage.transaction(write=False) as store:
        replay = _replay(store, slot, request_hash, 'export.create')
        if replay is not None:
            return replay
    with request.app.state.export_work.reserve(user['user_id']) as ticket:
        with storage.transaction() as store:
            replay = _replay(store, slot, request_hash, 'export.create')
            if replay is not None:
                return replay
            items = _snapshot_items(store, payload, request.app.state.limits)
            now = iso_utc()
            job = {
                "export_id": new_uuid7(),
                "format": payload.format,
                "filters": {
                    "uploaded_from": payload.uploaded_from.isoformat() if payload.uploaded_from else None,
                    "uploaded_to": payload.uploaded_to.isoformat() if payload.uploaded_to else None,
                    "final_cultivar_id": payload.final_cultivar_id,
                    "final_class_id": payload.final_class_id,
                    "format": payload.format,
                },
                "snapshot_at": now,
                "taxonomy_version": store.get_config()["taxonomy_version"],
                "item_count": len(items),
                "items": items,
                "status": "queued",
                "zip_key": None,
                "zip_sha256": None,
                "zip_size": None,
                "error_code": None,
                "error_detail": None,
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "owner_id": user["user_id"],
            }
            store.add_export(job)
            store.add_idempotency(slot, {"request_hash": request_hash, "export_id": job["export_id"]})
            created = _job_out(job)

        try:
            ticket.submit(_run_export, storage, files, created['export_id'], request.app.state.limits.export_max_bytes)
        except Exception:
            _mark_failed(storage, created['export_id'], 'UNAVAILABLE', '导出调度失败，可按原快照重试')
            raise
        return created


@router.get("/exports", tags=["exports"], summary="导出批次列表（按创建时间倒序）")
def list_exports(
    request: Request,
    user: dict[str, Any] = Depends(require_roles(*_ADMIN_ROLES)),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    storage: MetadataStorage = request.app.state.storage
    with storage.transaction(write=False) as store:
        result = store.list_exports(page, page_size)
        return {"items": [_job_out(job) for job in result.items],
                "page": page, "page_size": page_size, "total": result.total}



@router.get("/exports/{export_id}", tags=["exports"], summary="导出批次状态")
def get_export(export_id: str, request: Request,
               user: dict[str, Any] = Depends(require_roles(*_ADMIN_ROLES))) -> dict[str, Any]:
    # 只读状态，不推进任务；推进由创建/重试时的后台任务负责。
    storage: MetadataStorage = request.app.state.storage
    with storage.transaction(write=False) as store:
        job = store.get_export(export_id.lower())
        if job is None:
            raise DomainError(404, "NOT_FOUND", "导出批次不存在")
        return _job_out(job)


@router.post("/exports/{export_id}/retry", tags=["exports"], status_code=202, summary="失败批次按原快照重试")
def retry_export(
    export_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_roles(*_ADMIN_ROLES)),
    idempotency_key: str = Depends(_idempotency_key_header),
) -> dict[str, Any]:
    storage: MetadataStorage = request.app.state.storage
    files: FileStorage = request.app.state.files
    key = export_id.lower()
    slot = _idempotency_slot(user, "export.retry", idempotency_key)
    request_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()

    with storage.transaction(write=False) as store:
        replay = _replay(store, slot, request_hash, 'export.retry')
        if replay is not None:
            return replay
    with request.app.state.export_work.reserve(user['user_id']) as ticket:
        with storage.transaction() as store:
            replay = _replay(store, slot, request_hash, 'export.retry')
            if replay is not None:
                return replay
            job = store.get_export(key)
            if job is None:
                raise DomainError(404, "NOT_FOUND", "导出批次不存在")
            if job["status"] != "failed":
                raise DomainError(409, "STATE_CONFLICT", "只有失败的批次可以重试", {
                    "status": job["status"],
                })
            _check_retry_budget(store, job, request.app.state.limits)
            # 原 ID、原快照、原筛选：不重新选样，也不改 frozen items / snapshot_at。
            job["status"] = "queued"
            job["error_code"] = None
            job["error_detail"] = None
            job["started_at"] = None
            job["finished_at"] = None
            job["zip_key"] = None
            job["zip_sha256"] = None
            job["zip_size"] = None
            store.add_idempotency(slot, {"request_hash": request_hash, "export_id": job["export_id"]})
            queued = _job_out(job)

        try:
            ticket.submit(_run_export, storage, files, queued['export_id'], request.app.state.limits.export_max_bytes)
        except Exception:
            _mark_failed(storage, queued['export_id'], 'UNAVAILABLE', '导出调度失败，可按原快照重试')
            raise
        return queued


def _iter_chunks(handle: BinaryIO) -> Iterator[bytes]:
    """流式读取并在结束/中断时关闭句柄。"""
    try:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        handle.close()


@router.get("/exports/{export_id}/download", tags=["exports"], summary="下载 ZIP")
def download_export(export_id: str, request: Request,
                    user: dict[str, Any] = Depends(require_roles(*_ADMIN_ROLES))) -> StreamingResponse:
    storage: MetadataStorage = request.app.state.storage
    key = export_id.lower()
    with storage.transaction(write=False) as store:
        job = store.get_export(key)
        if job is None:
            raise DomainError(404, "NOT_FOUND", "导出批次不存在")
        if job.get("status") != "succeeded" or not job.get("zip_key"):
            raise DomainError(409, "STATE_CONFLICT", "导出尚未成功，不能下载", {
                "status": job.get("status"),
            })
        zip_key = str(job["zip_key"])

    files: FileStorage = request.app.state.files
    try:
        handle = files.open_read(zip_key)
    except (OSError, StorageUnavailable):
        raise DomainError(409, "STATE_CONFLICT", "导出文件不可用，不能下载", {
            "status": "succeeded",
        }) from None

    return StreamingResponse(
        _iter_chunks(handle),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ZIP_NAME_PREFIX}{key}.zip"'},
        background=BackgroundTask(handle.close),
    )


__all__ = ["router", "ExportCreateIn", "recover_interrupted"]
