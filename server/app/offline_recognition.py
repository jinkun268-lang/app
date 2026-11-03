"""Read and correct server-owned recognition records independently of training labels."""
from __future__ import annotations

import json
import asyncio
import anyio
from datetime import timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .common import DomainError, current_user, iso_utc, require_roles
from .diagnosis_records import Age, Crop, Part, public_record
from .data_access import OfflineFilter
from .recognition import RecognitionOut
from .uploads import _render_preview, stream_file

router = APIRouter(prefix='/api/v1/offline-recognitions', tags=['offline-recognitions'])
READ = ('collector', 'expert', 'super_admin')


class CorrectionEvent(BaseModel):
    version: int
    from_name: str
    from_class_id: str | None
    name: str
    class_id: str | None
    note: str
    operator: str
    operator_id: str
    corrected_at: AwareDatetime


class RecognitionRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    record_id: str
    owner_display_name: str
    state: Literal['receiving', 'complete']
    created_at: AwareDatetime
    uploaded_at: AwareDatetime | None
    updated_at: AwareDatetime | None = None
    current_name: str
    current_class_id: str | None
    correction_version: int
    correction_events: list[CorrectionEvent]
    image_url: str
    recognition: RecognitionOut | None
    sha256: str | None = None
    source: Literal['server', 'device']
    crop_id: Crop
    part: Part
    tree_age: Age
    symptom: str
    captured_at: AwareDatetime
    mime_type: str
    file_size: int
    device_model: str
    inference_status: Literal['awaiting_image', 'processing', 'succeeded', 'failed'] | None = None
    inference_error_code: str | None = None
    inference_error: str | None = None


class OfflinePage(BaseModel):
    items: list[RecognitionRecord]
    total: int
    page: int
    page_size: int
    categories: list[str]


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=100)
    class_id: str | None = Field(default=None, max_length=128)
    note: str = Field(default='', max_length=2000)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写修正结果')
        return value.strip()


def _owned(store, record_id, user):
    row = store.get_offline(record_id)
    if row is None or (row['owner_id'] != user['user_id'] and (user['role'] not in ('expert', 'super_admin') or row['state'] != 'complete')):
        raise DomainError(404, 'NOT_FOUND', '识别记录不存在或不可见')
    return row


def _public(store, row):
    return public_record(store, row)


@router.get('/events')
async def events(request: Request, authorization: str | None = Header(None),
                 _user: dict = Depends(require_roles('expert', 'super_admin'))):
    bus = request.app.state.recognition_events
    queue = bus.subscribe()
    async def stream():
        try:
            yield 'event: ready\ndata: {}\n\n'
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    event = None
                try:
                    active = await anyio.to_thread.run_sync(current_user, request, authorization)
                    if active['role'] not in ('expert', 'super_admin'):
                        break
                except DomainError:
                    break
                if event:
                    yield 'event: changed\ndata: ' + json.dumps(event) + '\n\n'
                else:
                    yield ': heartbeat\n\n'
        finally:
            bus.unsubscribe(queue)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache, private', 'X-Accel-Buffering': 'no'})


@router.get('', response_model=OfflinePage)
def list_records(request: Request, user: dict = Depends(require_roles(*READ)),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 names: list[str] = Query(default=[], max_length=100), status: Literal['original', 'corrected'] | None = None,
                 uploaded_from: AwareDatetime | None = None, uploaded_to: AwareDatetime | None = None,
                 query: str = Query('', max_length=100)):
    if uploaded_from and uploaded_to and uploaded_from >= uploaded_to:
        raise DomainError(422, 'VALIDATION_FAILED', '开始时间必须早于结束时间')
    owner = user['user_id'] if user['role'] == 'collector' else None
    with request.app.state.storage.transaction(write=False) as store:
        result = store.list_offline(OfflineFilter(owner, tuple(names), status,
            uploaded_from.astimezone(timezone.utc) if uploaded_from else None,
            uploaded_to.astimezone(timezone.utc) if uploaded_to else None, query.strip()), page, page_size)
        return dict(items=[_public(store, row) for row in result.items], total=result.total, page=page, page_size=page_size,
                    categories=store.offline_names(owner))


@router.get('/{record_id}', response_model=RecognitionRecord)
def detail(record_id: str, request: Request, user: dict = Depends(require_roles(*READ))):
    with request.app.state.storage.transaction(write=False) as store:
        return _public(store, _owned(store, record_id, user))


@router.patch('/{record_id}/correction', response_model=RecognitionRecord)
def correct(record_id: str, body: CorrectionIn, request: Request, user: dict = Depends(require_roles('expert', 'super_admin'))):
    with request.app.state.storage.transaction() as store:
        row = _owned(store, record_id, user)
        if row.get('inference_status') == 'processing':
            raise DomainError(409, 'RECOGNITION_IN_PROGRESS', '识别尚未完成，请等待结果后再修正')
        if row['correction_version'] != body.expected_version:
            raise DomainError(409, 'VERSION_CONFLICT', '记录已被其他人员修正，请重新打开后修改')
        name = body.name
        if body.class_id:
            category = store.get_class(body.class_id)
            if not category or not category['is_active']:
                raise DomainError(422, 'VALIDATION_FAILED', '修正类别不存在或已停用')
            name = category['name']
        if (name, body.class_id) == (row['current_name'], row['current_class_id']):
            raise DomainError(422, 'VALIDATION_FAILED', '修正结果与当前结果相同')
        version = row['correction_version'] + 1
        row['correction_events'] = [*row['correction_events'], dict(version=version, from_name=row['current_name'], from_class_id=row['current_class_id'],
            name=name, class_id=body.class_id, note=body.note.strip(), operator=user['display_name'], operator_id=user['user_id'], corrected_at=iso_utc())]
        row.update(current_name=name, current_class_id=body.class_id, correction_version=version)
        row['updated_at'] = iso_utc()
        result = _public(store, row)
    request.app.state.recognition_events.publish(record_id)
    return result


@router.get('/{record_id}/image')
async def image(record_id: str, request: Request, preview: bool = False, user: dict = Depends(require_roles(*READ))):
    with request.app.state.storage.transaction(write=False) as store:
        row = _owned(store, record_id, user)
        if row['state'] != 'complete':
            raise DomainError(404, 'NOT_FOUND', '图片尚未上传完成')
        key, mime = row['file_key'], row['declaration']['mime_type']
    files = request.app.state.files
    if preview:
        target = f'previews/{record_id}/1024.jpg'
        work = request.app.state.upload_work
        def render():
            if not files.exists(target):
                with files.open_read(key) as source:
                    files.write(target, _render_preview(source.read(), 1024))
        with work.admit():
            await work.run(render)
        key, mime = target, 'image/jpeg'
    return stream_file(files, key, mime, {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
