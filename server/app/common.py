"""跨模块公共件：统一错误、请求 ID、时间、UUIDv7、令牌校验与角色依赖。

公共HTTP约定与认证辅助函数；底层存储由应用注入。
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .state import hash_password, verify_password
from .data_access import DataTransaction, StorageConflict, StorageUnavailable, session_key

__all__ = [
    "CONTRACT_VERSION",
    "DomainError",
    "current_user",
    "require_roles",
    "hash_password",
    "verify_password",
    "session_key",
]

# 与 contracts/openapi.yaml 的 x-contract-version 保持一致。
CONTRACT_VERSION = "2.0.0"

ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=30)


class DomainError(Exception):
    """业务错误：由统一异常处理器转成固定 error 形状。"""

    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


# ---------------- 时间 ----------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    dt = value or utcnow()
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------- UUIDv7 ----------------
# Python 3.12 的 uuid 尚无 uuid7；按 RFC 9562 布局自建：48 位毫秒时间戳 + 版本 + 12 位序号 + 随机。
_LAST_MS = 0
_SEQ = 0
_UUID_LOCK = threading.Lock()


def new_uuid7() -> str:
    global _LAST_MS, _SEQ
    now_ms = int(time.time() * 1000)
    with _UUID_LOCK:
        if now_ms <= _LAST_MS:
            now_ms = _LAST_MS
            _SEQ = (_SEQ + 1) & 0x0FFF
        else:
            _LAST_MS = now_ms
            _SEQ = 0
        seq = _SEQ
    ts = now_ms & ((1 << 48) - 1)
    rand_b = int.from_bytes(secrets.token_bytes(8), "big") & ((1 << 62) - 1)
    value = (ts << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def new_token() -> str:
    """不透明随机访问/刷新令牌（非 JWT），通过存储接口保存会话，SQL仅存令牌摘要。"""
    return secrets.token_urlsafe(32)


# ---------------- 统一错误 ----------------

def error_payload(request: Request, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id_of(request),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(request, code, message, details),
        headers=response_headers(request),
    )


def response_headers(request: Request) -> dict[str, str]:
    return {"X-Request-Id": request_id_of(request), "Cache-Control": "no-store"}


def request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) and rid else new_uuid7()


def _accept_request_id(value: str | None) -> str:
    """只接受合法 UUID 的入站 X-Request-Id，避免响应字段违反契约的 uuid 格式。"""
    candidate = (value or "").strip()
    if not candidate or len(candidate) > 64:
        return new_uuid7()
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return new_uuid7()


async def request_context_middleware(request: Request, call_next: Callable[[Request], Any]):
    """注入/透传 X-Request-Id，并统一禁止缓存。"""
    request.state.request_id = _accept_request_id(request.headers.get("x-request-id"))
    response = await call_next(request)
    tag = request_id_of(request)
    response.headers["X-Request-Id"] = tag
    response.headers["Cache-Control"] = "no-store"
    return response


_STATUS_CODES = {
    400: "VALIDATION_FAILED",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",  # 未开放的方法不额外创造错误码
    409: "STATE_CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    503: "UNAVAILABLE",
}


def register_exception_handlers(app: Any) -> None:
    """注册统一错误处理；不向客户端泄露栈或框架默认 detail。"""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        response = error_response(request, exc.status_code, exc.code, exc.message, exc.details)
        if exc.status_code == 429:
            response.headers["Retry-After"] = str((exc.details or {}).get("retry_after_seconds", 2))
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors():
            loc = [str(part) for part in item.get("loc", ()) if part not in ("body", "query", "path", "header")]
            fields.append({"field": ".".join(loc) or "body", "reason": item.get("msg", "invalid")})
        return error_response(request, 422, "VALIDATION_FAILED", "请求字段校验失败", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status_code = exc.status_code
        code = _STATUS_CODES.get(status_code, "INTERNAL" if status_code >= 500 else "VALIDATION_FAILED")
        message = "资源不存在或不可见" if status_code == 404 else "请求无法处理"
        return error_response(request, status_code, code, message)

    @app.exception_handler(StorageConflict)
    async def _storage_conflict(request: Request, exc: StorageConflict) -> JSONResponse:
        # 记录版本过期或唯一键冲突：提示刷新后重试，不暴露底层记录内容。
        return error_response(request, 409, "STATE_CONFLICT", "数据已被其他会话更新，请刷新后重试")

    @app.exception_handler(StorageUnavailable)
    async def _storage_unavailable(request: Request, exc: StorageUnavailable) -> JSONResponse:
        import logging

        logging.getLogger("server").warning("存储不可用: %s", type(exc).__name__)
        return error_response(request, 503, "UNAVAILABLE", "数据库暂时不可用，请稍后重试")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 完整异常只写服务端日志，响应体保持固定形状。
        import logging

        logging.getLogger("server").exception("未处理异常: %s", type(exc).__name__)
        return error_response(request, 500, "INTERNAL", "服务端内部错误")


# ---------------- 会话与令牌 ----------------
# 记录结构（access / refresh 共用同一 session_id，便于 logout 整会话撤销）：
#   {"kind": "access"|"refresh", "session_id", "user_id",
#    "expires_at": datetime, "revoked": bool}
# 存储适配器负责令牌检索与摘要；SQL不保存原始token。
def create_session(store: DataTransaction, user: dict[str, Any]) -> dict[str, Any]:
    session_id = new_uuid7()
    access, refresh = new_token(), new_token()
    now = utcnow()
    for token, kind, ttl in ((access, "access", ACCESS_TOKEN_TTL), (refresh, "refresh", REFRESH_TOKEN_TTL)):
        store.add_session(token, {"kind": kind, "session_id": session_id,
                                  "user_id": user["user_id"], "expires_at": now + ttl, "revoked": False})
    return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
            "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()), "session_id": session_id}


def revoke_session(store: DataTransaction, session_id: str) -> None:
    store.revoke_session(session_id)


def find_user_by_id(store: DataTransaction, user_id: str) -> dict[str, Any] | None:
    return store.get_user(user_id)


def _invalid_token(reason: str, message: str) -> DomainError:
    return DomainError(401, "AUTH_INVALID", message, {"reason": reason})


def authenticate(store: DataTransaction, token: str, expected_kind: str) -> dict[str, Any]:
    """校验令牌并返回会话记录；过期与无效使用不同 reason 以便客户端精确刷新。

    令牌检索和摘要键由数据访问接口封装。
    """
    record = store.get_session(token)
    if record is None or record.get("revoked") or record.get("kind") != expected_kind:
        raise _invalid_token("revoked", "登录状态已失效，请重新登录")
    if record["expires_at"] <= utcnow():
        raise _invalid_token("expired", "登录已过期，请刷新令牌")
    return record


def session_user(store: DataTransaction, record: dict[str, Any]) -> dict[str, Any]:
    user = find_user_by_id(store, record["user_id"])
    if user is None:
        raise _invalid_token("revoked", "登录状态已失效，请重新登录")
    if not user.get("is_active", False):
        raise DomainError(403, "ACCOUNT_DISABLED", "账号已停用")
    return user


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise DomainError(401, "AUTH_REQUIRED", "缺少访问令牌", {"reason": "missing"})
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise DomainError(401, "AUTH_REQUIRED", "缺少访问令牌", {"reason": "malformed"})
    return value.strip()


def current_user(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """受信用户依赖：校验 Bearer 访问令牌，返回公开字段投影。

    事务只在依赖内部短暂持有：拿到用户快照后立即提交/释放，不跨整个请求持有 DB 锁。
    """
    token = bearer_token(authorization)
    storage = request.app.state.storage
    with storage.transaction(write=False) as store:
        record = authenticate(store, token, "access")
        user = session_user(store, record)
        session_id = record["session_id"]
        snapshot = {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
        }
    # 供 logout 等需要整会话撤销的接口复用，避免重复解析请求头。
    request.state.session_id = session_id
    return snapshot


def require_roles(*roles: str) -> Callable[..., dict[str, Any]]:
    """角色依赖工厂：Depends(require_roles("admin", "super_admin"))。"""
    allowed = frozenset(roles)

    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in allowed:
            raise DomainError(403, "FORBIDDEN", "无权限执行该操作", {"required_roles": sorted(allowed)})
        return user

    return dependency
