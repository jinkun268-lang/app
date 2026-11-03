"""Save a referenced original and default result before calling any model."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .common import DomainError, iso_utc
from .recognition_images import MAX_BYTES, original_key, publish_original

Crop = Literal['huyou', 'xiangyou', 'citrus']
Part = Literal['leaf', 'fruit', 'branch']
Age = Literal['adult', 'young', 'unknown']
DEFAULT_RESULT = '系统识别错误'


class DiagnosisInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    crop_id: Crop = 'huyou'
    part: Part = 'leaf'
    tree_age: Age = 'unknown'
    symptom: str = Field(default='', max_length=2000)
    captured_at: AwareDatetime
    mime_type: Literal['image/jpeg', 'image/png', 'image/webp']
    file_size: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    device_model: str = Field(default='', max_length=100)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def public_record(store, row):
    owner = store.get_user(row['owner_id'])
    declaration = row['declaration']
    recognition = declaration.get('recognition')
    return {key: row.get(key) for key in ('record_id', 'state', 'created_at', 'uploaded_at', 'current_name', 'current_class_id',
        'correction_version', 'correction_events', 'inference_status', 'inference_error_code', 'inference_error', 'updated_at')} | {
        'owner_display_name': owner['display_name'] if owner else '已停用账号', **declaration,
        'sha256': declaration.get('sha256') or (recognition or {}).get('sha256'),
        'image_url': f"/api/v1/offline-recognitions/{row['record_id']}/image"}


def _owner(row, user):
    if row is None or row['owner_id'] != user['user_id']:
        raise DomainError(404, 'NOT_FOUND', '识别记录不存在或不可见')


def prepare(storage, record_id, user, body):
    values = body.model_dump(mode='json')
    digest = fingerprint(values)
    with storage.transaction() as store:
        row = store.get_offline(record_id)
        if row:
            _owner(row, user)
            if row.get('inference_status') is not None:
                if row['declaration_hash'] != digest:
                    raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '同一识别编号的图片或现场信息不能改变')
            else:
                old = row['declaration']
                if any(old.get(key) != values[key] for key in ('crop_id', 'part', 'tree_age', 'mime_type', 'file_size')) or old['recognition']['sha256'] != body.sha256:
                    raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '同一识别编号已存在其他内容')
            return public_record(store, row)
        now = iso_utc()
        row = dict(record_id=record_id, owner_id=user['user_id'], declaration={**values, 'source': 'server', 'recognition': None},
            declaration_hash=digest, state='receiving', file_key=original_key(record_id, body.mime_type), created_at=now, uploaded_at=None,
            current_name=DEFAULT_RESULT, current_class_id=None, correction_version=0, correction_events=[],
            inference_status='awaiting_image', inference_error_code=None, inference_error=None, updated_at=now)
        store.add_offline(row)
        return public_record(store, row)


def accept_image(request, record_id, user, data, mime, crop_id, part, tree_age):
    """Commit the reference first; a published original always has a database record."""
    storage = request.app.state.storage
    digest = hashlib.sha256(data).hexdigest()
    with storage.transaction(write=False) as store:
        existing = store.get_offline(record_id)
        if existing:
            _owner(existing, user)
            values = existing['declaration']
            expected_sha = values.get('sha256') or (values.get('recognition') or {}).get('sha256')
            if (expected_sha, values['file_size'], values['mime_type'], values['crop_id'], values['part'], values['tree_age']) != (digest, len(data), mime, crop_id, part, tree_age):
                raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '同一识别编号的图片或现场信息不一致')
    if existing is None:
        prepare(storage, record_id, user, DiagnosisInput(crop_id=crop_id, part=part, tree_age=tree_age,
            captured_at=datetime.now(timezone.utc), mime_type=mime, file_size=len(data), sha256=digest))
    with storage.transaction() as store:
        row = store.get_offline(record_id)
        _owner(row, user)
        if row.get('inference_status') == 'processing':
            raise DomainError(409, 'RECOGNITION_IN_PROGRESS', '这张图片正在识别，请稍后刷新结果', {'record_id': record_id})
        if row.get('inference_status') == 'succeeded' or (row.get('inference_status') is None and row['state'] == 'complete' and row['declaration']['source'] == 'server'):
            return row['declaration']['recognition']
        if row.get('inference_status') is None:
            raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '已有记录不能改为新的服务端识别任务')
        row.update(inference_status='processing', inference_error=None, inference_error_code=None, updated_at=iso_utc())
        key = row['file_key']
    try:
        publish_original(request.app.state.files, key, data)
        with storage.transaction() as store:
            row = store.get_offline(record_id)
            row.update(state='complete', uploaded_at=row['uploaded_at'] or iso_utc(), updated_at=iso_utc())
    except BaseException:
        fail(request, record_id, 'IMAGE_SAVE_FAILED', '图片保存未完成，请重试上传')
        raise
    request.app.state.recognition_events.publish(record_id)
    return None


def succeed(request, record_id, recognition):
    with request.app.state.storage.transaction() as store:
        row = store.get_offline(record_id)
        row['declaration'] = {**row['declaration'], 'recognition': recognition.model_dump(mode='json')}
        top = max(recognition.candidates, key=lambda candidate: candidate.score)
        if row['correction_version'] == 0:
            row.update(current_name=top.name, current_class_id=top.class_id)
        row.update(inference_status='succeeded', inference_error_code=None, inference_error=None, updated_at=iso_utc())
    request.app.state.recognition_events.publish(record_id)


def fail(request, record_id, code, message):
    with request.app.state.storage.transaction() as store:
        row = store.get_offline(record_id)
        if row and row.get('inference_status') == 'processing':
            ready = request.app.state.files.exists(row['file_key'])
            row.update(inference_status='failed', inference_error_code=code, inference_error=message,
                       state='complete' if ready else 'receiving', uploaded_at=row['uploaded_at'] or (iso_utc() if ready else None), updated_at=iso_utc())
    request.app.state.recognition_events.publish(record_id)


def recover(storage, files):
    with storage.transaction() as store:
        for row in store.interrupted_offline():
            ready = files.exists(row['file_key'])
            row.update(inference_status='failed', inference_error_code='INFERENCE_INTERRUPTED',
                inference_error='上次识别已中断，可重试', state='complete' if ready else 'receiving',
                uploaded_at=row['uploaded_at'] or (iso_utc() if ready else None), updated_at=iso_utc())
