"""四步采集上传和鉴权媒体；元数据走短事务，原图与预览走文件接口。

上传与样本视图中的图片由存储适配器恢复共享引用；原始字节只落文件，
元数据保存file_key。单次请求继续限制为最多20MiB，不常驻保存图片字节。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .common import DomainError, current_user, iso_utc, new_uuid7, utcnow
from .data_access import DataTransaction

router = APIRouter(prefix="/api/v1")

# ---------------- 限制 ----------------
MAX_DECLARATION_BYTES = 64 * 1024            # 声明体
MAX_IMAGE_BYTES = 20 * 1024 * 1024           # 单图
MAX_TOTAL_BYTES = 120 * 1024 * 1024          # 清单合计
MAX_PIXELS = 50_000_000                      # 单图像素上限，防解压炸弹
MIN_IMAGES = 1
MAX_IMAGES = 12

_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_EXPECTED_FORMAT = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
# 上传会话严格只属于 collector 本人；admin/super_admin 通过 /samples 与 /media 查看，首版不代采集。
_UPLOAD_ROLES = frozenset({"collector"})
_MEDIA_READ_ROLES = frozenset({"expert", "admin", "super_admin"})

_UUID7_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TZ_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$")


# ---------------- 请求 DTO（字段与 contracts/openapi.yaml 一致） ----------------

class ImageDeclaration(BaseModel):
    """每图声明项；未知字段直接拒绝（extra=forbid）。"""

    model_config = ConfigDict(extra="forbid")

    image_id: str
    view_type: Literal["close_up", "context", "other"]
    captured_at: str
    device_timezone: str
    device_model: str | None = Field(max_length=64, description="必填但可为 null：无法获取时显式传 null")
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    file_size: int = Field(ge=1, le=MAX_IMAGE_BYTES)
    sha256: str

    @field_validator("image_id")
    @classmethod
    def _uuid7(cls, value: str) -> str:
        if not _UUID7_RE.match(value):
            raise ValueError("必须是 UUIDv7（小写连字符形式）")
        return value

    @field_validator("captured_at")
    @classmethod
    def _aware_time(cls, value: str) -> str:
        raw = value.strip()
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError("必须是 RFC3339 时间") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("必须带时区偏移（Z 或 ±hh:mm），无偏移的本地时间不接受")
        # 原始写法（含本地偏移）保留给样本；比较用的 UTC 规范化在 _canonical 里做。
        return value.strip()

    @field_validator("device_timezone")
    @classmethod
    def _timezone_name(cls, value: str) -> str:
        if not (1 <= len(value) <= 64) or not _TZ_NAME_RE.match(value):
            raise ValueError("必须是 IANA 时区名，如 Asia/Shanghai")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not _SHA256_RE.match(value):
            raise ValueError("必须是 64 位小写十六进制 SHA256")
        return value


class UploadDeclaration(BaseModel):
    """声明 DTO；实例化后即为该 sample_id 的固定清单。"""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    schema_version: Literal[1]
    tree_id: str | None = Field(default=None, max_length=64)
    cultivar_id: str
    part: Literal["leaf", "fruit", "branch", "insect", "other"]
    class_id: str
    symptoms: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)
    images: list[ImageDeclaration] = Field(min_length=MIN_IMAGES, max_length=MAX_IMAGES)

    @field_validator("sample_id")
    @classmethod
    def _uuid7(cls, value: str) -> str:
        if not _UUID7_RE.match(value):
            raise ValueError("必须是 UUIDv7（小写连字符形式）")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "UploadDeclaration":
        seen: set[str] = set()
        for image in self.images:
            if image.image_id in seen:
                raise ValueError(f"images 内 image_id 重复: {image.image_id}")
            seen.add(image.image_id)
            if image.width * image.height > MAX_PIXELS:
                raise ValueError(f"单图像素超过上限 {MAX_PIXELS}: {image.image_id}")
        return self


# ---------------- 响应模型 ----------------

class UploadStatusOut(BaseModel):
    upload_id: str
    sample_id: str
    state: Literal["receiving", "complete"]
    declared_at: str
    received_images: list[str]
    missing_images: list[str]
    invalid_images: list[str]


class UploadImageReceiptOut(BaseModel):
    upload_id: str
    image_id: str
    receive_status: Literal["received"] = "received"
    sha256: str
    file_size: int


class UploadCompleteResponseOut(BaseModel):
    upload_id: str
    sample_id: str
    state: Literal["complete"] = "complete"
    upload_completed_at: str
    image_count: int


class MediaPendingResponse(BaseModel):
    """仅当预览确实未就绪时使用；当前实现按请求同步生成，不主动返回 202。"""

    image_id: str
    state: Literal["pending"] = "pending"
    retry_after: int = 1


# ---------------- 请求体与校验工具 ----------------

def _validation_error(fields: list[dict[str, str]]) -> DomainError:
    return DomainError(422, "VALIDATION_FAILED", "请求字段校验失败", {"fields": fields})


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """逐块读取并限制总长度，避免无界 request.body() 占用内存。"""
    header_len = request.headers.get("content-length")
    if header_len and header_len.isdigit() and int(header_len) > limit:
        raise DomainError(413, "PAYLOAD_TOO_LARGE", "请求体超过允许大小", {"limit_bytes": limit})
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise DomainError(413, "PAYLOAD_TOO_LARGE", "请求体超过允许大小", {"limit_bytes": limit})
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_json(raw: bytes) -> Any:
    if not raw:
        raise _validation_error([{"field": "body", "reason": "missing"}])
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _validation_error([{"field": "body", "reason": "invalid_json"}]) from None


def _validate(model: type[BaseModel], payload: Any) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        fields = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item.get("loc", ())) or "body"
            fields.append({"field": loc or "body", "reason": item.get("msg", "invalid")})
        raise _validation_error(fields) from None


def _check_dictionary(store: DataTransaction, decl: UploadDeclaration) -> None:
    cultivar = store.get_cultivar(decl.cultivar_id)
    klass = store.get_class(decl.class_id)
    fields = []
    if cultivar is None or not cultivar.get("is_active"):
        fields.append({"field": "cultivar_id", "reason": "不在启用品种清单内"})
    if klass is None or not klass.get("is_active"):
        fields.append({"field": "class_id", "reason": "不在启用类别清单内"})
    if fields:
        raise DomainError(422, "VALIDATION_FAILED", "字典值无效", {"fields": fields})


# ---------------- 规范化与哈希 ----------------

def _utc_iso(value: str) -> str:
    """把带偏移的时间统一成 UTC，供规范化比较使用（同一时刻不同写法等价）。"""
    raw = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    return iso_utc(datetime.fromisoformat(raw))


def _canonical(decl: UploadDeclaration) -> dict[str, Any]:
    """规范化声明：保留全部采集字段（含 captured_at/sha256/file_size），只排除传输信息。

    `captured_at` 按 UTC 归一后参与比较；样本与响应仍保留客户端原始偏移写法。
    """
    images = []
    for image in decl.images:
        row = image.model_dump()
        row["captured_at"] = _utc_iso(image.captured_at)
        images.append(row)
    images.sort(key=lambda row: row["image_id"])
    return {
        "sample_id": decl.sample_id,
        "schema_version": decl.schema_version,
        "tree_id": decl.tree_id,
        "cultivar_id": decl.cultivar_id,
        "part": decl.part,
        "class_id": decl.class_id,
        "symptoms": decl.symptoms,
        "note": decl.note,
        "images": images,
    }


def _content_hash(canonical: dict[str, Any]) -> str:
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------- 查询工具 ----------------

_NOT_FOUND = "上传会话不存在或不可见"


def _require_upload_role(user: dict[str, Any]) -> None:
    if user["role"] not in _UPLOAD_ROLES:
        raise DomainError(403, "FORBIDDEN", "该角色无上传权限", {"required_roles": sorted(_UPLOAD_ROLES)})


def _owned_upload(store: DataTransaction, upload_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """owner 校验：非本人一律 404，不泄露会话存在性（管理员也不读上传会话）。"""
    upload = store.get_upload(upload_id)
    if upload is None:
        raise DomainError(404, "NOT_FOUND", _NOT_FOUND)
    if upload["owner_id"] != user["user_id"]:
        raise DomainError(404, "NOT_FOUND", _NOT_FOUND)
    return upload


def _upload_with_image(store: DataTransaction, image_id: str) -> dict[str, Any] | None:
    return store.find_upload_for_image(image_id)


def _status_out(upload: dict[str, Any]) -> UploadStatusOut:
    order = upload["image_order"]
    received: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for image_id in order:
        status = upload["images"][image_id]["receive_status"]
        if status == "received":
            received.append(image_id)
        elif status == "invalid":
            invalid.append(image_id)
        else:
            missing.append(image_id)
    return UploadStatusOut(
        upload_id=upload["upload_id"],
        sample_id=upload["sample_id"],
        state=upload["state"],
        declared_at=upload["declared_at"],
        received_images=received,
        missing_images=missing,
        invalid_images=invalid,
    )


def _receipt(upload: dict[str, Any], image: dict[str, Any]) -> UploadImageReceiptOut:
    return UploadImageReceiptOut(
        upload_id=upload["upload_id"],
        image_id=image["image_id"],
        receive_status="received",
        sha256=image["sha256"],
        file_size=image["file_size"],
    )


def _complete_out(upload: dict[str, Any]) -> UploadCompleteResponseOut:
    return UploadCompleteResponseOut(
        upload_id=upload["upload_id"],
        sample_id=upload["sample_id"],
        state="complete",
        upload_completed_at=upload["upload_completed_at"],
        image_count=len(upload["image_order"]),
    )


def _label(store: DataTransaction, kind: str, value: str) -> str:
    """字典显示名；字典项由配置模块维护，这里只读取当前名称。"""
    row = store.get_cultivar(value) if kind == "cultivar" else store.get_class(value)
    return row["name"] if row is not None else value


def _clock_skew(captured_at: str) -> bool:
    try:
        parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed - utcnow() > timedelta(hours=24)


# ---------------- 公开投影（review / export 复用） ----------------

def public_image(image: dict[str, Any]) -> dict[str, Any]:
    """SampleImage 投影：只含契约字段；内部 receive_status/sha256 不外泄。

    `captured_at` 对外统一成 UTC（内部仍保留客户端原始偏移写法，时刻不变）。
    """
    return {
        "image_id": image["image_id"],
        "view_type": image["view_type"],
        "captured_at": _utc_iso(image["captured_at"]),
        "device_timezone": image["device_timezone"],
        "device_model": image["device_model"],
        "mime_type": image["mime_type"],
        "width": image["width"],
        "height": image["height"],
        "file_size": image["file_size"],
        "quality_status": image["quality_status"],
        "quality_reason_code": image["quality_reason_code"],
        "quality_note": image["quality_note"],
        "quality_version": image["quality_version"],
        "quality_reviewed_by_display_name": image["quality_reviewed_by_display_name"],
        "quality_reviewed_at": image["quality_reviewed_at"],
        "clock_skew_suspected": image["clock_skew_suspected"],
        "quality_events": list(image["quality_events"]),
    }


def public_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """SampleDetail 投影（无果园）。仅 complete 样本可对客户端暴露；receiving 的 upload_completed_at 为 None。"""
    return {
        "sample_id": sample["sample_id"],
        "tree_id": sample["tree_id"],
        "original_cultivar_id": sample["original_cultivar_id"],
        "original_cultivar_name": sample["original_cultivar_name"],
        "original_part": sample["original_part"],
        "original_class_id": sample["original_class_id"],
        "original_class_name": sample["original_class_name"],
        "symptoms": sample["symptoms"],
        "note": sample["note"],
        "taxonomy_version": sample["taxonomy_version"],
        "upload_state": sample["upload_state"],
        "upload_completed_at": sample["upload_completed_at"],
        "excluded": sample["excluded"],
        "review_status": sample["review_status"],
        "final_cultivar_id": sample["final_cultivar_id"],
        "final_cultivar_name": sample["final_cultivar_name"],
        "final_part": sample["final_part"],
        "final_class_id": sample["final_class_id"],
        "final_class_name": sample["final_class_name"],
        "review_note": sample["review_note"],
        "review_version": sample["review_version"],
        "reviewed_by_display_name": sample["reviewed_by_display_name"],
        "reviewed_at": sample["reviewed_at"],
        "images": [public_image(image) for image in sample["images"]],
        "review_events": list(sample["review_events"]),
    }


# ---------------- 构造内部对象 ----------------

def _new_image(decl: ImageDeclaration) -> dict[str, Any]:
    """图片内部 dict；同一对象被 uploads[...] 与 samples[...] 共同引用。"""
    return {
        "image_id": decl.image_id,
        "view_type": decl.view_type,
        "captured_at": decl.captured_at,
        "device_timezone": decl.device_timezone,
        "device_model": decl.device_model,
        "mime_type": decl.mime_type,
        "width": decl.width,
        "height": decl.height,
        "file_size": decl.file_size,
        "sha256": decl.sha256,
        # 内部：接收状态，不进公开响应
        "receive_status": "missing",
        # 审核侧字段（初始 pending，由 review 模块维护）
        "quality_status": "pending",
        "quality_reason_code": None,
        "quality_note": None,
        "quality_version": 0,
        "quality_reviewed_by_display_name": None,
        "quality_reviewed_at": None,
        "clock_skew_suspected": _clock_skew(decl.captured_at),
        "quality_events": [],
    }


def _new_sample(store: DataTransaction, decl: UploadDeclaration, user: dict[str, Any], upload_id: str,
                images: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_id": decl.sample_id,
        "owner_id": user["user_id"],
        "upload_id": upload_id,
        "tree_id": decl.tree_id,
        "original_cultivar_id": decl.cultivar_id,
        "original_cultivar_name": _label(store, "cultivar", decl.cultivar_id),
        "original_part": decl.part,
        "original_class_id": decl.class_id,
        "original_class_name": _label(store, "class", decl.class_id),
        "symptoms": decl.symptoms,
        "note": decl.note,
        "taxonomy_version": store.get_config()["taxonomy_version"],
        "upload_state": "receiving",
        "upload_completed_at": None,
        "excluded": False,
        "review_status": "unreviewed",
        "final_cultivar_id": None,
        "final_cultivar_name": None,
        "final_part": None,
        "final_class_id": None,
        "final_class_name": None,
        "review_note": None,
        "review_version": 0,
        "reviewed_by_display_name": None,
        "reviewed_at": None,
        "images": images,
        "review_events": [],
    }


# ---------------- 字节校验 ----------------

def _require_headers(content_length: str | None, content_type: str | None, content_sha: str | None) -> None:
    missing = [
        {"field": name, "reason": "missing"}
        for name, value in (
            ("Content-Length", content_length),
            ("Content-Type", content_type),
            ("X-Content-SHA256", content_sha),
        )
        if not value
    ]
    if missing:
        raise _validation_error(missing)


def _check_declared_headers(declared: dict[str, Any], content_length: str, content_type: str,
                            content_sha: str) -> None:
    base_type = content_type.split(";")[0].strip().lower()
    if base_type not in _MIME_TYPES:
        raise DomainError(415, "UNSUPPORTED_MEDIA", "只接受 JPEG/PNG/WebP", {"content_type": base_type})
    if base_type != declared["mime_type"]:
        raise DomainError(409, "FILE_MISMATCH", "Content-Type 与声明的 mime_type 不一致", {
            "image_id": declared["image_id"], "reason": "mime_type",
            "expected": declared["mime_type"], "actual": base_type,
        })
    if not _SHA256_RE.match(content_sha):
        raise _validation_error([{"field": "X-Content-SHA256", "reason": "必须是 64 位小写十六进制 SHA256"}])
    if content_sha != declared["sha256"]:
        raise DomainError(409, "FILE_MISMATCH", "X-Content-SHA256 与声明不一致", {
            "image_id": declared["image_id"], "reason": "sha256_header",
            "expected": declared["sha256"], "actual": content_sha,
        })
    try:
        length = int(content_length)
    except ValueError:
        raise _validation_error([{"field": "Content-Length", "reason": "必须是整数"}]) from None
    if length != declared["file_size"]:
        raise DomainError(409, "FILE_MISMATCH", "Content-Length 与声明 file_size 不一致", {
            "image_id": declared["image_id"], "reason": "content_length",
            "expected": declared["file_size"], "actual": length,
        })


def _verify_decodable(data: bytes, declared: dict[str, Any]) -> None:
    """按真实字节核对签名、尺寸并完整解码；只读校验，不重编码。"""
    expected_format = _EXPECTED_FORMAT[declared["mime_type"]]
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").upper()
            width, height = image.size
            if fmt not in _EXPECTED_FORMAT.values():
                raise DomainError(415, "UNSUPPORTED_MEDIA", "只接受 JPEG/PNG/WebP 图片", {"format": fmt})
            if fmt != expected_format:
                raise DomainError(409, "FILE_MISMATCH", "文件签名与声明的 mime_type 不一致", {
                    "image_id": declared["image_id"], "reason": "signature",
                    "expected": expected_format, "actual": fmt,
                })
            if width * height > MAX_PIXELS:
                raise DomainError(413, "PAYLOAD_TOO_LARGE", "图像像素数超过上限", {"limit_pixels": MAX_PIXELS})
            if (width, height) != (declared["width"], declared["height"]):
                raise DomainError(409, "FILE_MISMATCH", "解码尺寸与声明不一致", {
                    "image_id": declared["image_id"], "reason": "dimensions",
                    "expected": [declared["width"], declared["height"]], "actual": [width, height],
                })
            # 头信息通过后再完整解码，确认可解码且触发解压炸弹检查。
            image.load()
    except DomainError:
        raise
    except Image.DecompressionBombError:
        raise DomainError(413, "PAYLOAD_TOO_LARGE", "图像像素数超过上限", {"limit_pixels": MAX_PIXELS}) from None
    except Exception:
        raise DomainError(415, "UNSUPPORTED_MEDIA", "图片无法解码", {"image_id": declared["image_id"]}) from None


def _mark_invalid(storage: Any, upload_id: str, image_id: str) -> None:
    with storage.transaction() as store:
        upload = store.get_upload(upload_id)
        if upload is None:
            return
        image = upload["images"].get(image_id)
        if image is not None and image["receive_status"] != "received":
            image["receive_status"] = "invalid"


# ---------------- 四步接口 ----------------

@router.post("/uploads", tags=["uploads"], status_code=201, response_model=UploadStatusOut,
             summary="声明样本与固定图片清单（第 1 步）")
async def declare_upload(request: Request,
                         user: dict[str, Any] = Depends(current_user)) -> Response:
    _require_upload_role(user)
    work = request.app.state.upload_work
    with work.admit():
        raw = await _read_body_limited(request, MAX_DECLARATION_BYTES)
        return await work.run(_declare_received, request.app.state.storage, user, raw)


def _declare_received(storage, user, raw):
    decl = _validate(UploadDeclaration, _decode_json(raw))
    with storage.transaction(write=False) as store:
        _check_dictionary(store, decl)
    total = sum(image.file_size for image in decl.images)
    if total > MAX_TOTAL_BYTES:
        raise DomainError(413, "PAYLOAD_TOO_LARGE", "声明清单合计大小超过上限", {
            "limit_bytes": MAX_TOTAL_BYTES, "actual_bytes": total,
        })

    canonical = _canonical(decl)
    content_hash = _content_hash(canonical)

    with storage.transaction() as store:
        existing_sample = store.get_sample(decl.sample_id)
        if existing_sample is not None:
            if existing_sample["owner_id"] != user["user_id"]:
                # 不泄露图片信息，也不暴露已有会话内容。
                raise DomainError(403, "FORBIDDEN", "该 sample_id 已被其他账号声明")
            upload = store.get_upload(existing_sample["upload_id"])
            if upload["content_hash"] != content_hash:
                raise DomainError(409, "IDEMPOTENCY_CONFLICT", "同一 sample_id 的声明内容不同", {
                    "sample_id": decl.sample_id, "reason": "declaration_changed",
                })
            # 同声明重放：200 + 同一 upload_id，不新建会话。
            return JSONResponse(status_code=200, content=_status_out(upload).model_dump())

        for image in decl.images:
            owner_upload = _upload_with_image(store, image.image_id)
            if owner_upload is not None:
                raise DomainError(409, "STATE_CONFLICT", "图片 ID 已被其他样本占用", {
                    "image_id": image.image_id,
                })

        upload_id = new_uuid7()
        images = [_new_image(image) for image in decl.images]
        upload = {
            "upload_id": upload_id,
            "sample_id": decl.sample_id,
            "owner_id": user["user_id"],
            "state": "receiving",
            "declared_at": iso_utc(),
            "upload_completed_at": None,
            "content_hash": content_hash,
            "declaration": canonical,
            "image_order": [image["image_id"] for image in images],
            "images": {image["image_id"]: image for image in images},
        }
        store.add_collection(upload, _new_sample(store, decl, user, upload_id, images))
        return JSONResponse(status_code=201, content=_status_out(upload).model_dump())


@router.get("/uploads/{upload_id}", tags=["uploads"], response_model=UploadStatusOut,
            summary="查询上传状态与缺图清单（第 3 步）")
def get_upload_status(upload_id: str, request: Request,
                      user: dict[str, Any] = Depends(current_user)) -> UploadStatusOut:
    storage = request.app.state.storage
    _require_upload_role(user)
    with storage.transaction() as store:
        upload = _owned_upload(store, upload_id, user)
        for image in upload["images"].values():
            if image["receive_status"] == "received" and not request.app.state.files.exists(original_key(image)):
                image["receive_status"] = "missing"
        return _status_out(upload)


@router.put("/uploads/{upload_id}/images/{image_id}", tags=["uploads"], status_code=201,
            response_model=UploadImageReceiptOut, summary="逐图上传原始字节（第 2 步）")
async def upload_image_bytes(
    upload_id: str,
    image_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    content_length: str | None = Header(default=None),
    content_type: str | None = Header(default=None),
    content_sha: str | None = Header(default=None, alias="X-Content-SHA256"),
) -> Response:
    _require_upload_role(user)
    work = request.app.state.upload_work
    with work.admit():
        declared = await work.run(_prepare_image, request.app.state.storage, user,
                                  upload_id, image_id, content_length, content_type, content_sha)
        data = await _read_body_limited(request, MAX_IMAGE_BYTES)
        return await work.run(_store_image, request.app.state.storage, request.app.state.files,
                              user, upload_id, image_id, declared, data)


def _prepare_image(storage, user, upload_id, image_id, content_length, content_type, content_sha):
    with storage.transaction(write=False) as store:
        upload = _owned_upload(store, upload_id, user)
        image = upload["images"].get(image_id)
        if image is None:
            raise DomainError(409, "STATE_CONFLICT", "图片不在声明的固定清单内", {"image_id": image_id})
        if upload["state"] == "complete":
            raise DomainError(409, "STATE_CONFLICT", "上传已完成，拒绝新字节", {"upload_id": upload_id})
        declared = dict(image)  # 读请求体期间不改动声明

    _require_headers(content_length, content_type, content_sha)
    _check_declared_headers(declared, content_length, content_type, content_sha)  # type: ignore[arg-type]

    return declared


def _store_image(storage, files, user, upload_id, image_id, declared, data):
    if len(data) != declared["file_size"]:
        _mark_invalid(storage, upload_id, image_id)
        raise DomainError(409, "FILE_MISMATCH", "实际字节数与声明 file_size 不一致", {
            "image_id": image_id, "reason": "byte_length",
            "expected": declared["file_size"], "actual": len(data),
        })
    digest = hashlib.sha256(data).hexdigest()
    if digest != declared["sha256"]:
        _mark_invalid(storage, upload_id, image_id)
        raise DomainError(409, "FILE_MISMATCH", "实际字节 SHA256 与声明不一致", {
            "image_id": image_id, "reason": "sha256_body",
            "expected": declared["sha256"], "actual": digest,
        })
    try:
        _verify_decodable(data, declared)
    except DomainError:
        _mark_invalid(storage, upload_id, image_id)
        raise

    with storage.transaction() as store:
        upload = _owned_upload(store, upload_id, user)
        image = upload["images"][image_id]
        if upload["state"] == "complete":
            raise DomainError(409, "STATE_CONFLICT", "上传已完成，拒绝新字节", {"upload_id": upload_id})
        file_key = original_key(image)
        if image["receive_status"] == "received" and files.exists(file_key):
            if image["sha256"] == digest and image["file_size"] == len(data):
                return JSONResponse(status_code=200, content=_receipt(upload, image).model_dump())
            raise DomainError(409, "FILE_MISMATCH", "该图片已接收不同字节", {"image_id": image_id})
        # Publish before confirming receipt. If DB commit fails, retry reuses the immutable key.
        files.write(file_key, data)
        image["file_key"] = file_key
        image["receive_status"] = "received"
        image["sha256"] = digest
        image["file_size"] = len(data)
        return JSONResponse(status_code=201, content=_receipt(upload, image).model_dump())


@router.post("/uploads/{upload_id}/complete", tags=["uploads"], response_model=UploadCompleteResponseOut,
             summary="确认接收完成（第 4 步）")
def complete_upload(upload_id: str, request: Request,
                    user: dict[str, Any] = Depends(current_user)) -> UploadCompleteResponseOut:
    storage = request.app.state.storage
    _require_upload_role(user)
    with storage.transaction() as store:
        upload = _owned_upload(store, upload_id, user)
        if upload["state"] == "complete":
            return _complete_out(upload)

        received: list[str] = []
        missing: list[str] = []
        invalid: list[str] = []
        for iid in upload["image_order"]:
            status = upload["images"][iid]["receive_status"]
            if status == "received" and request.app.state.files.exists(original_key(upload["images"][iid])):
                received.append(iid)
            elif status == "invalid":
                invalid.append(iid)
            else:
                missing.append(iid)
        if missing or invalid:
            raise DomainError(409, "MISSING_IMAGES", "仍有未收到或无效的图片", {
                "upload_id": upload_id,
                "missing": missing,
                "invalid": invalid,
                "received": received,
            })

        completed_at = iso_utc()
        upload["state"] = "complete"
        upload["upload_completed_at"] = completed_at
        sample = store.get_sample(upload["sample_id"])
        sample["upload_state"] = "complete"
        sample["upload_completed_at"] = completed_at
        return _complete_out(upload)


def original_key(image: dict[str, Any]) -> str:
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[image["mime_type"]]
    return image.get("file_key") or f"originals/{image['image_id']}.{ext}"


def stream_file(files: Any, key: str, media_type: str, headers: dict[str, str] | None = None) -> Response:
    try:
        source = files.open_read(key)
    except FileNotFoundError:
        raise DomainError(404, "NOT_FOUND", "文件不存在") from None

    def chunks():
        try:
            while chunk := source.read(256 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(chunks(), media_type=media_type, headers=headers,
                             background=BackgroundTask(source.close))


# ---------------- 媒体 ----------------

def _render_preview(data: bytes, target_width: int) -> bytes:
    """按 EXIF 方向纠正后缩放到目标宽度，输出 JPEG(quality=80)，不携带 EXIF/GPS。"""
    try:
        with Image.open(io.BytesIO(data)) as source:
            # 先看头部尺寸再解码，避免解压炸弹。
            if source.width * source.height > MAX_PIXELS:
                raise DomainError(413, "PAYLOAD_TOO_LARGE", "图像像素数超过上限", {"limit_pixels": MAX_PIXELS})
            source.load()
            upright = ImageOps.exif_transpose(source) or source
            if upright.width > target_width:
                height = max(1, round(upright.height * target_width / upright.width))
                upright = upright.resize((target_width, height), Image.LANCZOS)
            if upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")
            out = io.BytesIO()
            # 不传 exif/icc_profile：生成图自动去掉原图元数据（含 GPS）。
            upright.save(out, format="JPEG", quality=80)
            return out.getvalue()
    except DomainError:
        raise
    except Image.DecompressionBombError:
        raise DomainError(413, "PAYLOAD_TOO_LARGE", "图像像素数超过上限", {"limit_pixels": MAX_PIXELS}) from None
    except Exception:
        raise DomainError(415, "UNSUPPORTED_MEDIA", "原图无法生成预览") from None


@router.get("/media/sample-images/{image_id}", tags=["media"], summary="鉴权访问样本图片（原图或预览）")
def get_sample_image(
    image_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    variant: str = "original",
    w: int | None = None,
) -> Response:
    storage = request.app.state.storage
    with storage.transaction(write=False) as store:
        upload = store.find_upload_for_image(image_id)
        if upload is None:
            raise DomainError(404, "NOT_FOUND", "图片不存在或不可见")
        image = upload["images"][image_id]
        if upload["owner_id"] != user["user_id"] and user["role"] not in _MEDIA_READ_ROLES:
            raise DomainError(403, "FORBIDDEN", "无权访问该图片")

    files = request.app.state.files
    file_key = original_key(image)
    if not files.exists(file_key):
        raise DomainError(404, "NOT_FOUND", "原图尚未接收或文件缺失")
    if variant not in ("preview", "original"):
        raise _validation_error([{"field": "variant", "reason": "只允许 preview 或 original"}])
    if variant == "original":
        return stream_file(files, file_key, image["mime_type"], {"ETag": image["sha256"]})
    target = 320 if w is None else w
    if target not in (320, 1024):
        raise _validation_error([{"field": "w", "reason": "只允许 320 或 1024"}])
    preview_key = f"previews/{image_id}/{target}.jpg"
    if not files.exists(preview_key):
        with files.open_read(file_key) as source:
            preview = _render_preview(source.read(), target)
        files.write(preview_key, preview)
    return stream_file(files, preview_key, "image/jpeg", {"ETag": f"{image['sha256']}-{target}"})



__all__ = [
    "router",
    "public_sample",
    "public_image",
    "UploadDeclaration",
    "ImageDeclaration",
    "MediaPendingResponse",
    "MAX_DECLARATION_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_TOTAL_BYTES",
    "MAX_PIXELS",
]
