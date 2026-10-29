"""跨设备采集批次及由专家真实答复的图文咨询。"""
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .common import DomainError, current_user, iso_utc, require_roles
from .uploads import public_sample

router = APIRouter(prefix='/api/v1')

class BatchIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=128)
    place: str = Field(default='', max_length=256)
    collector: str = Field(default='', max_length=128)
    default_cultivar_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    closed: bool = False
    created_at: datetime | None = None

    @field_validator('created_at')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('created_at 必须包含时区')
        return value

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('名称不能为空')
        return value.strip()

class QuestionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    text: str = Field(min_length=1, max_length=2000)
    sample_id: str | None = Field(default=None, max_length=36)

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('问题不能为空')
        return value.strip()

class AnswerIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator('answer')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('答复不能为空')
        return value.strip()

def _page(result, page, page_size, project=lambda x: x):
    return {'items': [project(row) for row in result.items], 'total': result.total, 'page': page, 'page_size': page_size}

def _owner(user):
    return user['user_id'] if user['role'] == 'collector' else None

def _question(store, qid, user):
    row = store.get_question(qid)
    if row is None or (row['owner_id'] != user['user_id'] and user['role'] not in ('expert', 'super_admin')):
        raise DomainError(404, 'NOT_FOUND', '咨询不存在或不可见')
    return row

def question_detail(store, row):
    sample = store.get_sample(row['sample_id']) if row['sample_id'] else None
    if sample is not None and sample['upload_state'] != 'complete':
        sample = None
    return {**row, 'sample': public_sample(sample) if sample else None,
            'images': [{'image_id': image['image_id'],
                        'preview_url': f"/api/v1/media/sample-images/{image['image_id']}?variant=preview&w=320",
                        'original_url': f"/api/v1/media/sample-images/{image['image_id']}"}
                       for image in sample['images']] if sample else []}

@router.put('/batches/{batch_id}', tags=['batches'])
def put_batch(batch_id: str, body: BatchIn, request: Request,
              user: dict[str, Any] = Depends(require_roles('collector', 'super_admin'))):
    if not batch_id or len(batch_id) > 64:
        raise DomainError(422, 'VALIDATION_FAILED', '批次 ID 长度无效')
    with request.app.state.storage.transaction() as store:
        row = store.get_batch(batch_id)
        if row is not None and row['owner_id'] != user['user_id']:
            raise DomainError(404, 'NOT_FOUND', '批次不存在或不可修改')
        if body.default_cultivar_id:
            cultivar = store.get_cultivar(body.default_cultivar_id)
            if cultivar is None or not cultivar['is_active']:
                raise DomainError(422, 'VALIDATION_FAILED', '默认品种不存在或已停用')
        values = body.model_dump(exclude={'created_at'})
        now = iso_utc()
        if row is None:
            row = {**values, 'batch_id': batch_id, 'owner_id': user['user_id'],
                   'created_at': body.created_at.isoformat() if body.created_at else now, 'updated_at': now}
            store.add_batch(row)
        else:
            row.update(values, updated_at=now)
        return dict(row)

@router.get('/batches', tags=['batches'])
def list_batches(request: Request, user: dict = Depends(require_roles('collector', 'expert', 'admin', 'super_admin')),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with request.app.state.storage.transaction(write=False) as store:
        return _page(store.list_batches(_owner(user), page, page_size), page, page_size)

@router.post('/questions', tags=['questions'], status_code=201)
def create_question(body: QuestionIn, request: Request, response: Response,
                    user: dict = Depends(require_roles('collector', 'super_admin'))):
    with request.app.state.storage.transaction() as store:
        existing = store.get_question(body.question_id)
        if existing:
            _question(store, body.question_id, user)
            if existing['owner_id'] != user['user_id'] or existing['text'] != body.text or existing['sample_id'] != body.sample_id:
                raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '同一咨询 ID 的内容不同')
            response.status_code = 200
            return question_detail(store, existing)
        if body.sample_id:
            sample = store.get_sample(body.sample_id)
            if sample is None or sample['owner_id'] != user['user_id'] or sample['upload_state'] != 'complete':
                raise DomainError(404, 'NOT_FOUND', '只能关联本人已上传样本')
        row = {**body.model_dump(), 'owner_id': user['user_id'], 'status': 'open', 'answer': None,
               'created_at': iso_utc(), 'answered_at': None}
        store.add_question(row)
        return question_detail(store, row)

@router.get('/questions', tags=['questions'])
def list_questions(request: Request, user: dict = Depends(require_roles('collector', 'expert', 'super_admin')),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with request.app.state.storage.transaction(write=False) as store:
        return _page(store.list_questions(_owner(user), page, page_size), page, page_size,
                     lambda row: question_detail(store, row))

@router.get('/questions/{question_id}', tags=['questions'])
def get_question(question_id: str, request: Request, user: dict = Depends(current_user)):
    with request.app.state.storage.transaction(write=False) as store:
        return question_detail(store, _question(store, question_id, user))

@router.patch('/questions/{question_id}/answer', tags=['questions'])
def answer_question(question_id: str, body: AnswerIn, request: Request,
                    user: dict = Depends(require_roles('expert', 'super_admin'))):
    with request.app.state.storage.transaction() as store:
        row = _question(store, question_id, user)
        row.update(answer=body.answer, status='answered', answered_at=iso_utc())
        return question_detail(store, row)
