"""Immutable original-image storage shared by inference and recognition archives."""
from __future__ import annotations

import hashlib
import io

from PIL import Image, UnidentifiedImageError

from .common import DomainError

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 24_000_000
EXTENSIONS = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


def original_key(image_id: str, mime: str) -> str:
    return f'originals/{image_id}.{EXTENSIONS[mime]}'


def validate_original(data: bytes, mime: str) -> None:
    if not 0 < len(data) <= MAX_BYTES:
        raise DomainError(413, 'PAYLOAD_TOO_LARGE', '原图为空或超过20MiB')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise DomainError(413, 'PAYLOAD_TOO_LARGE', '图片不能超过2400万像素')
            if Image.MIME.get(image.format) != mime or getattr(image, 'is_animated', False):
                raise ValueError('format')
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError(415, 'UNSUPPORTED_MEDIA', '请上传完整的静态JPEG、PNG或WebP原图') from exc


def publish_original(files, key: str, data: bytes) -> None:
    """Publish bytes already checked by validate_original; never replace existing content."""
    digest = hashlib.sha256(data).digest()
    if not files.exists(key) and files.write(key, data):
        return
    with files.open_read(key) as existing:
        stored = hashlib.sha256()
        for chunk in iter(lambda: existing.read(256 * 1024), b''):
            stored.update(chunk)
    if stored.digest() != digest:
        raise DomainError(409, 'IDEMPOTENCY_CONFLICT', '图片编号已被其他内容占用')
