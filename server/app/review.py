"""采集记录、专业核验和训练质量；元数据经统一对象事务持久化。

范围与规则（与 contracts/openapi.yaml 的 samples 路径和 Schema 对应）：

- 默认只列 `upload_state=complete` 的样本；admin/super_admin 可见全部已完整接收的样本，
  collector 仅列出／读取本人样本；expert 核验，admin 做训练质量，super_admin 可跨区。
- 列表筛选：review_status（逗号分隔多值）、excluded、final_cultivar_id、final_class_id、
  uploaded_from/uploaded_to（北京时间整日，左闭右开）、q（sample_id 精确或 tree_id 前缀）、
  page/page_size（默认 1/20，最大 100）；不合法参数返回 422。
- 排序固定 `upload_completed_at desc, sample_id desc`。
- 只有 complete 样本可写审核；`expected_version` 必须是**非负整数**（拒绝 bool/浮点/字符串），
  与当前 `review_version` / `quality_version` 不符返回 409 `VERSION_CONFLICT`。
- confirmed = 采集原值三项；corrected 三项齐全且至少一项与原值不同，字典项必须存在且启用；
  unresolved 不得出现 final_* 字段（连 null 也不行），成功后 final_* 清为 null，原值保留；
  不允许提交 unreviewed。
- 单图质量只写 usable/unusable，unusable 必须给有效 reason；quality_version 与 review_version 独立。
- 每次成功写入同时递增对应版本并追加相应历史事件，整体在一个元数据事务内原子完成；
  不引入额外审计系统。
- 对外一律经 `uploads.public_sample` / `uploads.public_image` 投影，不暴露 owner/upload_id/
  图片 sha256/receive_status 等内部字段。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .data_access import DataTransaction, SampleFilter
from .common import DomainError, current_user, iso_utc, new_uuid7, require_roles
from .uploads import public_image, public_sample

router = APIRouter(prefix="/api/v1")

_ADMIN_ROLES = frozenset({"admin", "super_admin"})
_REVIEW_ROLES = frozenset({"expert", "super_admin"})
_READ_ALL_ROLES = _ADMIN_ROLES | _REVIEW_ROLES
_BEIJING = timezone(timedelta(hours=8))

_REVIEW_STATUSES = ("unreviewed", "confirmed", "corrected", "unresolved")
_UPLOAD_STATES = ("receiving", "complete")
_REASON_CODES = ("blur", "occluded", "exposure", "wrong_object", "duplicate", "other")

_FINAL_FIELDS = ("final_cultivar_id", "final_part", "final_class_id")
_ORIGINAL_FIELDS = ("original_cultivar_id", "original_part", "original_class_id")


# ---------------- 时间与查询工具 ----------------

def parse_utc(value: str | None) -> datetime | None:
    """把 ISO 时间解析成 UTC datetime；解析失败返回 None。"""
    if not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def beijing_day_bound(day: date, *, end: bool) -> datetime:
    """北京时间整日边界：end=False 为当日 00:00，end=True 为次日 00:00（开区间上界）。"""
    boundary = datetime.combine(day, time.min, tzinfo=_BEIJING)
    if end:
        boundary += timedelta(days=1)
    return boundary.astimezone(timezone.utc)


def _validation_error(fields: list[dict[str, str]]) -> DomainError:
    return DomainError(422, "VALIDATION_FAILED", "请求字段校验失败", {"fields": fields})


# ---------------- 请求 DTO ----------------

class SampleReviewIn(BaseModel):
    """对象审核请求；final_* 用 model_fields_set 区分“未提供”与“显式 null”。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt = Field(ge=0)
    review_status: Literal["confirmed", "corrected", "unresolved"]
    final_cultivar_id: str | None = None
    final_part: Literal["leaf", "fruit", "branch", "insect", "other"] | None = None
    final_class_id: str | None = None
    review_note: str | None = Field(default=None, max_length=500)


class ImageQualityIn(BaseModel):
    """单图质量请求；expected_version 对应该图 quality_version。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt = Field(ge=0)
    quality_status: Literal["usable", "unusable"]
    quality_reason_code: str | None = None
    quality_note: str | None = Field(default=None, max_length=200)


class ExcludeRestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt = Field(ge=0)
    reason: str | None = Field(default=None, max_length=500)


# ---------------- 访问控制 ----------------

_NOT_FOUND = "样本不存在或不可见"


def _sample_or_404(store: DataTransaction, sample_id: str) -> dict[str, Any]:
    sample = store.get_sample(sample_id)
    if sample is None:
        raise DomainError(404, "NOT_FOUND", _NOT_FOUND)
    return sample


def _check_readable(sample: dict[str, Any], user: dict[str, Any]) -> None:
    """核验与训练人员读全部；采集人员仅可读取自己的原记录。"""
    role = user["role"]
    if role in _READ_ALL_ROLES:
        return
    if role == "collector":
        if sample["owner_id"] != user["user_id"]:
            raise DomainError(404, "NOT_FOUND", _NOT_FOUND)
        return
    raise DomainError(403, "FORBIDDEN", "该角色无样本权限", {"required_roles": sorted(_ADMIN_ROLES)})


def _check_writable(sample: dict[str, Any]) -> None:
    if sample["upload_state"] != "complete":
        raise DomainError(409, "STATE_CONFLICT", "样本尚未完成接收，不能写入审核", {
            "upload_state": sample["upload_state"],
        })


def _check_version(current: int, expected: int, *, current_field: str) -> None:
    if expected != current:
        raise DomainError(409, "VERSION_CONFLICT", "数据已被他人更新，请保留本地修改并刷新后再提交", {
            "field": current_field,
            "current_version": current,
        })


# ---------------- 字典与投影 ----------------

def _class_row(store: DataTransaction, class_id: str | None) -> dict[str, Any] | None:
    if class_id is None:
        return None
    return store.get_class(class_id)


def _cultivar_row(store: DataTransaction, cultivar_id: str | None) -> dict[str, Any] | None:
    if cultivar_id is None:
        return None
    return store.get_cultivar(cultivar_id)


def _display_name(row: dict[str, Any] | None, value: str | None) -> str | None:
    if value is None:
        return None
    return row["name"] if row is not None else value


def _summary(sample: dict[str, Any]) -> dict[str, Any]:
    """SampleSummary 投影（列表用）；SampleSummary 要求 upload_completed_at 非空。"""
    images = sample["images"]
    return {
        "sample_id": sample["sample_id"],
        "tree_id": sample["tree_id"],
        **{key: sample.get(key) for key in ("batch_id", "batch_snapshot", "latitude", "longitude", "location_accuracy_m")},
        "original_cultivar_id": sample["original_cultivar_id"],
        "original_cultivar_name": sample["original_cultivar_name"],
        "original_part": sample["original_part"],
        "original_class_id": sample["original_class_id"],
        "original_class_name": sample["original_class_name"],
        "final_cultivar_id": sample["final_cultivar_id"],
        "final_cultivar_name": sample["final_cultivar_name"],
        "final_part": sample["final_part"],
        "final_class_id": sample["final_class_id"],
        "final_class_name": sample["final_class_name"],
        "review_status": sample["review_status"],
        "excluded": sample["excluded"],
        "upload_completed_at": sample["upload_completed_at"],
        "image_count": len(images),
        "first_image_id": images[0]["image_id"] if images else None,
    }


# ---------------- 列表与详情 ----------------

@router.get("/samples", tags=["samples"], summary="样本列表（分页、筛选）")
def list_samples(
    request: Request,
    user: dict[str, Any] = Depends(require_roles("collector", "expert", "admin", "super_admin")),
    upload_state: str | None = Query(default=None),
    review_status: str | None = Query(default=None, description="多值用逗号分隔"),
    excluded: bool | None = Query(default=None),
    final_cultivar_id: str | None = Query(default=None),
    final_class_id: str | None = Query(default=None),
    batch_id: str | None = Query(default=None, max_length=64),
    uploaded_from: date | None = Query(default=None, description="北京时间整日 YYYY-MM-DD"),
    uploaded_to: date | None = Query(default=None, description="北京时间整日 YYYY-MM-DD"),
    q: str | None = Query(default=None, max_length=36, description="sample_id 精确或 tree_id 前缀"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    storage = request.app.state.storage

    if upload_state is not None and upload_state not in _UPLOAD_STATES:
        raise _validation_error([{"field": "upload_state", "reason": "只允许 receiving 或 complete"}])
    # 当前对外只暴露 complete 样本：receiving 的 upload_completed_at 为空，无法满足 SampleSummary 契约。
    if upload_state == "receiving":
        raise _validation_error([{"field": "upload_state", "reason": "当前版本只提供 complete 样本"}])

    statuses: list[str] | None = None
    if review_status is not None and review_status.strip() != "":
        statuses = [part.strip() for part in review_status.split(",") if part.strip()]
        invalid = [value for value in statuses if value not in _REVIEW_STATUSES]
        if invalid:
            raise _validation_error([{"field": "review_status", "reason": f"未知审核状态：{invalid[0]}"}])

    lower = beijing_day_bound(uploaded_from, end=False) if uploaded_from else None
    upper = beijing_day_bound(uploaded_to, end=True) if uploaded_to else None
    needle = (q or "").strip().lower()

    filters = SampleFilter(batch_id=batch_id, review_statuses=tuple(statuses) if statuses is not None else None,
                           excluded=excluded, final_cultivar_id=final_cultivar_id,
                           final_class_id=final_class_id, uploaded_from=lower,
                           uploaded_to=upper, query=needle,
                           owner_id=user["user_id"] if user["role"] == "collector" else None)
    with storage.transaction(write=False) as store:
        result = store.list_samples(filters, page, page_size)
        return {"items": [_summary(sample) for sample in result.items],
                "page": page, "page_size": page_size, "total": result.total}



@router.get("/samples/{sample_id}", tags=["samples"], summary="样本详情")
def get_sample(sample_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    storage = request.app.state.storage
    with storage.transaction(write=False) as store:
        sample = _sample_or_404(store, sample_id.lower())
        _check_readable(sample, user)
        if sample["upload_state"] != "complete":
            # 未完成接收的样本不作为可审核对象暴露，避免返回契约外的空 upload_completed_at。
            raise DomainError(404, "NOT_FOUND", _NOT_FOUND)
        return public_sample(sample)


# ---------------- 对象审核 ----------------

def _review_value_errors(store: DataTransaction, sample: dict[str, Any], payload: SampleReviewIn) -> list[dict[str, str]]:
    provided = payload.model_fields_set
    fields: list[dict[str, str]] = []

    if payload.review_status == "unresolved":
        extra = [name for name in _FINAL_FIELDS if name in provided]
        for name in extra:
            fields.append({"field": name, "reason": "unresolved 不得包含 final_* 字段"})
        return fields

    if payload.review_status == "confirmed":
        for name, original in zip(_FINAL_FIELDS, _ORIGINAL_FIELDS):
            if name not in provided:
                continue  # 未提供则按采集原值写入
            if getattr(payload, name) != sample[original]:
                fields.append({"field": name, "reason": "confirmed 必须等于采集原值"})
        return fields

    # corrected：三项齐全、至少一项与原值不同、字典项存在且启用
    missing = [name for name in _FINAL_FIELDS if name not in provided or getattr(payload, name) is None]
    for name in missing:
        fields.append({"field": name, "reason": "corrected 必须提供最终品种/部位/类别"})
    if missing:
        return fields

    if all(getattr(payload, name) == sample[original] for name, original in zip(_FINAL_FIELDS, _ORIGINAL_FIELDS)):
        fields.append({"field": "review_status", "reason": "corrected 至少一项需与原值不同"})

    cultivar = _cultivar_row(store, payload.final_cultivar_id)
    if cultivar is None or not cultivar.get("is_active", False):
        fields.append({"field": "final_cultivar_id", "reason": "品种不存在或已停用"})
    klass = _class_row(store, payload.final_class_id)
    if klass is None or not klass.get("is_active", False):
        fields.append({"field": "final_class_id", "reason": "类别不存在或已停用"})
    return fields


@router.patch("/samples/{sample_id}/review", tags=["samples"], summary="保存对象审核")
def review_sample(
    sample_id: str,
    payload: SampleReviewIn,
    request: Request,
    user: dict[str, Any] = Depends(require_roles("expert", "super_admin")),
) -> dict[str, Any]:
    storage = request.app.state.storage
    key = sample_id.lower()
    with storage.transaction() as store:
        sample = _sample_or_404(store, key)
        _check_writable(sample)
        _check_version(sample["review_version"], payload.expected_version, current_field="review_version")
        fields = _review_value_errors(store, sample, payload)
        if fields:
            raise _validation_error(fields)

        if payload.review_status == "confirmed":
            final_values = {name: sample[original] for name, original in zip(_FINAL_FIELDS, _ORIGINAL_FIELDS)}
        elif payload.review_status == "corrected":
            final_values = {
                "final_cultivar_id": payload.final_cultivar_id,
                "final_part": payload.final_part,
                "final_class_id": payload.final_class_id,
            }
        else:
            final_values = {name: None for name in _FINAL_FIELDS}

        before = {
            "review_status": sample["review_status"],
            "final_cultivar_id": sample["final_cultivar_id"],
            "final_part": sample["final_part"],
            "final_class_id": sample["final_class_id"],
            "review_note": sample["review_note"],
        }
        now = iso_utc()
        sample["review_status"] = payload.review_status
        sample["final_cultivar_id"] = final_values["final_cultivar_id"]
        sample["final_cultivar_name"] = _display_name(
            _cultivar_row(store, final_values["final_cultivar_id"]), final_values["final_cultivar_id"]
        )
        sample["final_part"] = final_values["final_part"]
        sample["final_class_id"] = final_values["final_class_id"]
        sample["final_class_name"] = _display_name(
            _class_row(store, final_values["final_class_id"]), final_values["final_class_id"]
        )
        sample["review_note"] = payload.review_note
        sample["review_version"] += 1
        sample["reviewed_by_display_name"] = user["display_name"]
        sample["reviewed_at"] = now

        after = {
            "review_status": sample["review_status"],
            "final_cultivar_id": sample["final_cultivar_id"],
            "final_part": sample["final_part"],
            "final_class_id": sample["final_class_id"],
            "review_note": sample["review_note"],
        }
        sample["review_events"].insert(0, {
            "review_id": new_uuid7(),
            "action": "review",
            "actor_display_name": user["display_name"],
            "actor_role": user["role"],
            "at": now,
            "note": payload.review_note,
            "sample_version": sample["review_version"],
            "before_json": before,
            "after_json": after,
        })
        return public_sample(sample)


# ---------------- 单图质量 ----------------

@router.patch("/samples/{sample_id}/images/{image_id}/quality", tags=["samples"], summary="单图质量")
def set_image_quality(
    sample_id: str,
    image_id: str,
    payload: ImageQualityIn,
    request: Request,
    user: dict[str, Any] = Depends(require_roles("admin", "super_admin")),
) -> dict[str, Any]:
    storage = request.app.state.storage
    key = sample_id.lower()
    with storage.transaction() as store:
        sample = _sample_or_404(store, key)
        _check_writable(sample)
        if sample["review_status"] not in ("confirmed", "corrected"):
            raise DomainError(409, "STATE_CONFLICT", "样本尚未通过专业核验，不能保存训练质量", {
                "review_status": sample["review_status"],
            })
        image = next((item for item in sample["images"] if item["image_id"] == image_id.lower()), None)
        if image is None:
            raise DomainError(404, "NOT_FOUND", "图片不存在或不属于该样本")
        _check_version(image["quality_version"], payload.expected_version, current_field="quality_version")

        fields: list[dict[str, str]] = []
        reason = payload.quality_reason_code
        if payload.quality_status == "unusable":
            if reason is None or reason not in _REASON_CODES:
                fields.append({"field": "quality_reason_code", "reason": "不可用必须给出有效原因"})
        elif reason is not None:
            fields.append({"field": "quality_reason_code", "reason": "可用图片不应带不可用原因"})
        if fields:
            raise _validation_error(fields)

        before_status = image["quality_status"]
        now = iso_utc()
        image["quality_status"] = payload.quality_status
        image["quality_reason_code"] = reason if payload.quality_status == "unusable" else None
        image["quality_note"] = payload.quality_note
        image["quality_version"] += 1
        image["quality_reviewed_by_display_name"] = user["display_name"]
        image["quality_reviewed_at"] = now
        image["quality_events"].insert(0, {
            "event_id": new_uuid7(),
            "before_status": before_status,
            "after_status": payload.quality_status,
            "reason_code": image["quality_reason_code"],
            "note": payload.quality_note,
            "actor_display_name": user["display_name"],
            "at": now,
            "image_version": image["quality_version"],
        })
        return public_image(image)


# ---------------- 排除 / 恢复 ----------------

def _set_excluded(sample_id: str, payload: ExcludeRestoreIn, request: Request, user: dict[str, Any],
                  *, excluded: bool) -> dict[str, Any]:
    storage = request.app.state.storage
    key = sample_id.lower()
    action = "exclude" if excluded else "restore"
    with storage.transaction() as store:
        sample = _sample_or_404(store, key)
        _check_writable(sample)
        _check_version(sample["review_version"], payload.expected_version, current_field="review_version")
        if bool(sample["excluded"]) is excluded:
            raise DomainError(409, "STATE_CONFLICT", "样本已处于该状态", {
                "excluded": bool(sample["excluded"]),
            })

        now = iso_utc()
        sample["excluded"] = excluded
        sample["review_version"] += 1
        sample["reviewed_by_display_name"] = user["display_name"]
        sample["reviewed_at"] = now
        sample["review_events"].insert(0, {
            "review_id": new_uuid7(),
            "action": action,
            "actor_display_name": user["display_name"],
            "actor_role": user["role"],
            "at": now,
            "note": payload.reason,
            "sample_version": sample["review_version"],
            "before_json": {"excluded": not excluded},
            "after_json": {"excluded": excluded},
        })
        return public_sample(sample)


@router.post("/samples/{sample_id}/exclude", tags=["samples"], summary="排除样本")
def exclude_sample(
    sample_id: str,
    payload: ExcludeRestoreIn,
    request: Request,
    user: dict[str, Any] = Depends(require_roles("admin", "super_admin")),
) -> dict[str, Any]:
    return _set_excluded(sample_id, payload, request, user, excluded=True)


@router.post("/samples/{sample_id}/restore", tags=["samples"], summary="恢复样本")
def restore_sample(
    sample_id: str,
    payload: ExcludeRestoreIn,
    request: Request,
    user: dict[str, Any] = Depends(require_roles("admin", "super_admin")),
) -> dict[str, Any]:
    return _set_excluded(sample_id, payload, request, user, excluded=False)


__all__ = [
    "router",
    "parse_utc",
    "beijing_day_bound",
    "SampleReviewIn",
    "ImageQualityIn",
    "ExcludeRestoreIn",
]
