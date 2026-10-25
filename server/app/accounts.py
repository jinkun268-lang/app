"""账号管理接口（仅超级管理员）。

元数据经 storage.transaction() 读写（默认 SQLite，可换 MySQL/PostgreSQL，测试用内存实现），
不引入版本字段、审计模块或删除接口；密码只存 PBKDF2 散列。
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from .data_access import DataTransaction
from .common import (
    DomainError,
    find_user_by_id,
    hash_password,
    iso_utc,
    new_uuid7,
    require_roles,
)

router = APIRouter(prefix="/api/v1/admin", tags=["users"])

RoleName = Literal["collector", "admin", "super_admin", "expert"]

_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")
# 去掉易混淆字符，保证人工抄写临时密码不容易出错。
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PASSWORD_LENGTH = 16


class UserOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: RoleName
    is_active: bool
    created_at: str
    last_login_at: str | None = None


class UserPage(BaseModel):
    items: list[UserOut]
    page: int
    page_size: int
    total: int


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    display_name: str
    role: RoleName


class UserCreateResponse(BaseModel):
    user: UserOut
    temporary_password: str


class UserPatchRequest(BaseModel):
    """只允许显示名/角色/启停；登录名不可改，未知字段直接 422。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    role: RoleName | None = None
    is_active: StrictBool | None = None


class ResetPasswordResponse(BaseModel):
    temporary_password: str


# ---------------- 内部工具 ----------------

def _field_error(field: str, reason: str) -> DomainError:
    return DomainError(422, "VALIDATION_FAILED", "请求字段校验失败", {"fields": [{"field": field, "reason": reason}]})


def _normalize_display_name(value: Any) -> str:
    text = str(value).strip()
    if not (1 <= len(text) <= 64):
        raise _field_error("display_name", "去首尾空白后需为 1–64 个字符")
    return text


def _normalize_username(value: Any) -> str:
    text = "" if value is None else str(value)
    if not _USERNAME_RE.match(text):
        raise _field_error("username", "需符合 ^[a-z][a-z0-9_.-]{2,31}$")
    return text


def _generate_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


def _revoke_user_sessions(store: DataTransaction, user_id: str) -> None:
    """撤销目标账号全部 access/refresh 记录（保留记录本身，只置 revoked）。"""
    store.revoke_user_sessions(user_id)


def _user_out(user: dict[str, Any]) -> UserOut:
    """显式投影：不返回 password。"""
    return UserOut(
        user_id=user["user_id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
        last_login_at=user["last_login_at"],
    )


def _find_or_404(store: DataTransaction, user_id: str) -> dict[str, Any]:
    user = find_user_by_id(store, user_id)
    if user is None:
        raise DomainError(404, "NOT_FOUND", "账号不存在", {"resource": "user"})
    return user


# ---------------- 接口 ----------------

@router.get("/users", response_model=UserPage, summary="账号列表（分页）")
def list_users(
    request: Request,
    caller: dict[str, Any] = Depends(require_roles("super_admin")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> UserPage:
    with request.app.state.storage.transaction(write=False) as store:
        result = store.list_users(page, page_size)
        items = [_user_out(user) for user in result.items]
    return UserPage(items=items, page=page, page_size=page_size, total=result.total)



@router.post("/users", status_code=201, response_model=UserCreateResponse, summary="新建账号（一次性返回临时密码）")
def create_user(
    payload: UserCreateRequest,
    request: Request,
    caller: dict[str, Any] = Depends(require_roles("super_admin")),
) -> UserCreateResponse:
    username = _normalize_username(payload.username)
    display_name = _normalize_display_name(payload.display_name)
    with request.app.state.storage.transaction() as store:
        if store.find_user(username) is not None:
            raise DomainError(
                409,
                "STATE_CONFLICT",
                "登录名已存在",
                {"object": "user", "field": "username", "current_state": "exists"},
            )
        temporary_password = _generate_password()
        user = {
            "user_id": new_uuid7(),
            "username": username,
            "display_name": display_name,
            "role": payload.role,
            "is_active": True,
            "password_hash": hash_password(temporary_password),
            "created_at": iso_utc(),
            "last_login_at": None,
        }
        store.add_user(user)
        created = _user_out(user)
    return UserCreateResponse(user=created, temporary_password=temporary_password)


@router.patch("/users/{user_id}", response_model=UserOut, summary="改名/角色/启停（无硬删除）")
def update_user(
    user_id: str,
    payload: UserPatchRequest,
    request: Request,
    caller: dict[str, Any] = Depends(require_roles("super_admin")),
) -> UserOut:
    provided = payload.model_dump(exclude_unset=True)
    if not provided:
        raise _field_error("body", "至少提供一个字段（display_name/role/is_active）")
    null_fields = [name for name, value in provided.items() if value is None]
    if null_fields:
        raise _field_error(null_fields[0], "不得为 null；不修改请省略该字段")

    with request.app.state.storage.transaction() as store:
        target = _find_or_404(store, user_id)
        is_self = target["user_id"] == caller["user_id"]
        new_role = provided.get("role", target["role"])
        new_active = provided.get("is_active", target["is_active"])
        display_name = (
            _normalize_display_name(provided["display_name"]) if "display_name" in provided else target["display_name"]
        )

        if is_self and new_active is False:
            raise DomainError(409, "STATE_CONFLICT", "不能停用当前登录账号", {"object": "user", "current_state": "self"})
        if is_self and new_role != target["role"]:
            raise DomainError(409, "STATE_CONFLICT", "不能修改自己的角色", {"object": "user", "current_state": "self"})

        loses_super = target["role"] == "super_admin" and (new_role != "super_admin" or new_active is False)
        if loses_super:
            others = [
                u
                for u in store.active_superadmins()
                if u["user_id"] != target["user_id"]
            ]
            if not others:
                raise DomainError(
                    409,
                    "STATE_CONFLICT",
                    "至少保留一个启用的超级管理员",
                    {"object": "user", "current_state": "last_super_admin"},
                )

        role_changed = new_role != target["role"]
        disabling = target["is_active"] and not new_active
        target["display_name"] = display_name
        target["role"] = new_role
        target["is_active"] = new_active
        if role_changed or disabling:
            # 角色变化或停用后旧会话立即失效；重新启用不恢复旧会话。
            _revoke_user_sessions(store, target["user_id"])
        return _user_out(target)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse, summary="重置密码（一次性返回临时密码）")
def reset_password(
    user_id: str,
    request: Request,
    caller: dict[str, Any] = Depends(require_roles("super_admin")),
) -> ResetPasswordResponse:
    with request.app.state.storage.transaction() as store:
        target = _find_or_404(store, user_id)
        temporary_password = _generate_password()
        target["password_hash"] = hash_password(temporary_password)
        # 旧密码立即失效，同时撤销该账号全部令牌；is_active 不变。允许给自己重置。
        _revoke_user_sessions(store, target["user_id"])
    return ResetPasswordResponse(temporary_password=temporary_password)


__all__ = ["router", "UserOut", "UserPage", "UserCreateRequest", "UserPatchRequest", "ResetPasswordResponse"]
