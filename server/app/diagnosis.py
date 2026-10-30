"""Independent diagnoses: server-signed inference receipts and approved local knowledge."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool

from .common import DomainError, require_roles
from .recognition import RecognitionOut, recognize

router = APIRouter(prefix='/api/v1')
Crop = Literal['huyou', 'xiangyou', 'citrus']
Part = Literal['leaf', 'fruit', 'branch']
Age = Literal['adult', 'young', 'unknown']
Status = Literal['matched', 'uncertain', 'healthy', 'unmapped', 'conflict', 'unavailable']


class Action(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=3000)


class Source(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: HttpUrl


class Advice(BaseModel):
    status: Status
    title: str
    message: str
    actions: list[Action] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    version: str | None = None


class DiagnosisOut(BaseModel):
    recognition: RecognitionOut
    advice: Advice
    receipt: str


class RetryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    receipt: str = Field(min_length=1, max_length=24000)


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    class_id: str = Field(min_length=1)
    approved: StrictBool
    crop_ids: list[Crop] = Field(min_length=1)
    parts: list[Part] = Field(min_length=1)
    tree_ages: list[Age] = Field(min_length=1)
    kind: Literal['condition', 'healthy'] = 'condition'
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=3000)
    actions: list[Action] = Field(max_length=20)
    sources: list[Source] = Field(min_length=1, max_length=20)


class Knowledge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = Field(min_length=1, max_length=100)
    entries: list[Entry]


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str
    expires: int
    recognition: RecognitionOut
    crop_id: Crop
    part: Part
    tree_age: Age


def signing_key(root: Path) -> bytes:
    configured = os.environ.get('APP_DIAGNOSIS_SECRET')
    if configured is not None:
        if len(configured.encode()) < 32:
            raise RuntimeError('APP_DIAGNOSIS_SECRET must contain at least 32 bytes')
        return configured.encode()
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'diagnosis-secret'
    try:
        with target.open('xb') as handle:
            os.chmod(target, 0o600)
            handle.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    key = target.read_bytes()
    if len(key) != 32:
        raise RuntimeError('Invalid diagnosis signing key')
    return key


def sign(payload: Receipt, key: bytes) -> str:
    body = base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode().rstrip('=')
    return body + '.' + hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


def verify(value: str, key: bytes, user_id: str) -> Receipt:
    try:
        body, signature = value.split('.')
        expected = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('signature')
        payload = Receipt.model_validate_json(base64.b64decode(body + '=' * (-len(body) % 4), altchars=b'-_', validate=True))
        if payload.expires <= time.time():
            raise ValueError('expired')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise DomainError(422, 'INVALID_RECEIPT', '识别凭据无效或已过期，请重新识别') from exc
    if payload.user_id != user_id:
        raise DomainError(403, 'RECEIPT_FORBIDDEN', '不能使用其他账号的识别凭据')
    return payload


def advise(payload: Receipt, request: Request) -> Advice:
    candidates = sorted(payload.recognition.candidates, key=lambda c: c.score, reverse=True)
    top = candidates[0]
    if top.score < .80 or (len(candidates) > 1 and top.score - candidates[1].score < .20 - 1e-12):
        return Advice(status='uncertain', title='暂时无法确定', message='候选结果不够明确，请补拍清晰近照或咨询专业人员，暂不据此处理。')
    if payload.recognition.scope != payload.part:
        return Advice(status='conflict', title='照片部位与模型范围不符', message='请按所选部位重新拍照；当前结果不能提供处理方案。')
    if top.class_id is None:
        return Advice(status='unmapped', title='尚无对应资料', message='识别类别尚未映射到经审核的资料，请咨询专业人员。')
    with request.app.state.storage.transaction(write=False) as store:
        row = store.get_class(top.class_id)
        if row is None or not row.get('is_active'):
            return Advice(status='unmapped', title='类别已停用', message='当前类别已不可用，请重新识别或咨询专业人员。')
    configured = os.environ.get('APP_DIAGNOSIS_KNOWLEDGE', '')
    try:
        if not configured:
            raise ValueError('not configured')
        path = Path(configured)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('too large')
        knowledge = Knowledge.model_validate_json(path.read_bytes())
        if not knowledge.entries:
            raise ValueError('empty')
    except (OSError, ValueError):
        return Advice(status='unavailable', title='建议资料暂不可用', message='识别结果已保留，可稍后重试获取建议；处理前请咨询专业人员。')
    entries = [e for e in knowledge.entries if e.approved and e.class_id == top.class_id]
    if not entries:
        return Advice(status='unmapped', title='暂无已审核建议', message='该类别尚无已审核资料，请咨询专业人员。', version=knowledge.version)
    applicable = [e for e in entries if payload.crop_id in e.crop_ids and payload.part in e.parts and payload.tree_age in e.tree_ages]
    if len(applicable) != 1:
        return Advice(status='conflict', title='资料适用条件不明确', message='当前作物、部位或树龄与资料不符，或存在多条冲突资料，请咨询专业人员。', version=knowledge.version)
    item = applicable[0]
    return Advice(status='healthy' if item.kind == 'healthy' else 'matched', title=item.title, message=item.message,
                  actions=[] if item.kind == 'healthy' else item.actions, sources=item.sources, version=knowledge.version)


@router.post('/diagnoses', response_model=DiagnosisOut, tags=['diagnosis'])
async def diagnose(request: Request, image_id: str = Header(alias='X-Image-ID'),
                   crop_id: Crop = 'huyou', part: Part = 'leaf', tree_age: Age = 'unknown',
                   user: dict = Depends(require_roles('collector'))) -> DiagnosisOut:
    recognition = await recognize(request, image_id, user)
    payload = Receipt(user_id=user['user_id'], expires=int(time.time()) + 30 * 86400,
                      recognition=recognition, crop_id=crop_id, part=part, tree_age=tree_age)
    return DiagnosisOut(recognition=recognition, advice=advise(payload, request), receipt=sign(payload, request.app.state.diagnosis_key))


@router.post('/diagnoses/advice', response_model=Advice, tags=['diagnosis'])
def retry_advice(body: RetryIn, request: Request, user: dict = Depends(require_roles('collector'))) -> Advice:
    return advise(verify(body.receipt, request.app.state.diagnosis_key, user['user_id']), request)
