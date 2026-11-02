"""Batch-oriented training views over uploaded, non-excluded images."""
from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from .common import DomainError, require_roles
from .data_access import SampleFilter
from .review import beijing_day_bound, parse_utc
from .uploads import public_image

router = APIRouter(prefix='/api/v1/training', tags=['training'])
REVIEWED = ('confirmed', 'corrected')


def batch_in_dates(batch, lower: date | None, upper: date | None):
    created = parse_utc(batch.get('created_at'))
    return (created is not None
            and (lower is None or created >= beijing_day_bound(lower, end=False))
            and (upper is None or created < beijing_day_bound(upper, end=True)))


def sample_dimensions(sample):
    prefix = 'final' if sample['review_status'] in REVIEWED else 'original'
    return {name: sample.get(f'{prefix}_{name}') for name in
            ('class_id', 'class_name', 'cultivar_id', 'cultivar_name')}


def batch_samples(store, batch_id):
    page = 1
    while True:
        result = store.list_samples(SampleFilter(batch_id=batch_id, excluded=False), page, 100)
        yield from result.items
        if page * 100 >= result.total:
            break
        page += 1


def candidate_images(store, batch_id, class_ids=(), cultivar_ids=(), reviewed_only=False):
    for sample in batch_samples(store, batch_id):
        if reviewed_only and sample['review_status'] not in REVIEWED:
            continue
        dimensions = sample_dimensions(sample)
        if class_ids and dimensions['class_id'] not in class_ids:
            continue
        if cultivar_ids and dimensions['cultivar_id'] not in cultivar_ids:
            continue
        for image in sample['images']:
            if image['receive_status'] == 'received':
                yield sample, image, dimensions


def validate_dates(lower, upper):
    if lower and upper and lower > upper:
        raise DomainError(422, 'VALIDATION_FAILED', '结束日期不能早于开始日期')


@router.get('/batches')
def list_training_batches(request: Request,
                          user: dict = Depends(require_roles('admin', 'super_admin')),
                          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with request.app.state.storage.transaction(write=False) as store:
        result = store.list_batches(None, page, page_size)
        rows = []
        for batch in result.items:
            counts = dict(image_count=0, reviewed_count=0, pending_count=0, usable_count=0, unusable_count=0)
            for sample, image, _ in candidate_images(store, batch['batch_id']):
                counts['image_count'] += 1
                if sample['review_status'] in REVIEWED:
                    counts['reviewed_count'] += 1
                    counts[f"{image['quality_status']}_count"] += 1
            rows.append({**batch, **counts})
        return dict(items=rows, total=result.total, page=page, page_size=page_size)


@router.get('/batches/{batch_id}/images')
def list_training_images(batch_id: str, request: Request,
                         user: dict = Depends(require_roles('admin', 'super_admin')),
                         page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                         reviewed_only: bool = False):
    with request.app.state.storage.transaction(write=False) as store:
        if store.get_batch(batch_id) is None:
            raise DomainError(404, 'NOT_FOUND', '采集批次不存在')
        rows, total = [], 0
        start, end = (page - 1) * page_size, page * page_size
        for sample, image, dimensions in candidate_images(store, batch_id, reviewed_only=reviewed_only):
            if start <= total < end:
                rows.append({**public_image(image), **dimensions, 'sample_id': sample['sample_id'],
                             'batch_id': sample.get('batch_id'), 'tree_id': sample['tree_id'],
                             'review_status': sample['review_status'], 'uploaded_at': sample['upload_completed_at']})
            total += 1
        return dict(items=rows, total=total, page=page, page_size=page_size)
