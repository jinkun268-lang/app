"""Authenticated, bounded single-image inference. Images are temporary, never training labels."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from .common import DomainError, iso_utc, require_roles
from .resources import UploadWork

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 24_000_000
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class Candidate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    class_id: str | None = None


class RecognitionOut(BaseModel):
    image_id: str
    sha256: str
    model: str
    model_version: str
    scope: str
    candidates: list[Candidate] = Field(min_length=1, max_length=5)
    warning: str
    created_at: str


class LocalClassifier:
    """Only administrator-configured executables and manifests can be launched, without a shell."""
    def __init__(self, root: Path):
        self.root = root

    def predict(self, image: bytes) -> dict[str, Any]:
        python = os.environ.get("APP_RECOGNITION_PYTHON", "")
        manifest = os.environ.get("APP_RECOGNITION_MANIFEST", "")
        if not python or not manifest or not Path(python).is_file() or not Path(manifest).is_file():
            raise DomainError(503, "MODEL_UNAVAILABLE", "识别模型尚未配置，请先手动填写")
        work = self.root / "recognition-temp"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="image-", dir=work) as folder:
            target = Path(folder) / "image.jpg"
            target.write_bytes(image)
            try:
                result = subprocess.run([python, str(Path(__file__).resolve().parents[1] / "tools" / "classify_image.py"),
                                         "--manifest", manifest, "--image", str(target)],
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode != 0:
                    raise ValueError("Classifier process failed")
                data = json.loads(result.stdout)
                if not isinstance(data, dict):
                    raise ValueError("Invalid classifier response")
                return data
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                raise DomainError(503, "MODEL_UNAVAILABLE", "识别服务暂时不可用，照片已保留，可稍后重试") from exc


class LocalDetector:
    """前置 YOLO 检测：只读取管理员配置的本地权重，不下载模型。

    检测结果只用来回答“画面里有没有叶片”，并给出最大叶片框供分类裁剪；
    检测器不可用时返回 None，识别退回纯分类，不阻断主链路。
    """
    def __init__(self, root: Path, manifest: str | None = None):
        self.root = root
        # 未显式配置时不启用检测闸门，测试与未部署检测器的环境保持原行为。
        configured = manifest or os.environ.get("APP_RECOGNITION_DETECT_MANIFEST", "")
        self.manifest = Path(configured) if configured else None

    def detect(self, image: bytes) -> tuple[dict[str, Any] | None, bytes | None]:
        if self.manifest is None or not self.manifest.is_file():
            return None, None
        try:
            config = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("detector manifest unreadable", exc_info=True)
            return None, None
        python = os.environ.get("APP_RECOGNITION_DETECT_PYTHON") or str(config.get("python") or "")
        if not python or not Path(python).is_file():
            logger.warning("detector python missing: %s", python)
            return None, None
        work = self.root / "recognition-temp"
        work.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="detect-", dir=work) as folder:
                target = Path(folder) / "image.jpg"
                target.write_bytes(image)
                crop = Path(folder) / "crop.jpg"
                result = subprocess.run(
                    [python, str(Path(__file__).resolve().parents[1] / "tools" / "detect_image.py"),
                     "--manifest", str(self.manifest), "--image", str(target), "--crop-out", str(crop)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode != 0:
                    raise ValueError("Detector process failed")
                data = json.loads(result.stdout)
                if not isinstance(data, dict):
                    raise ValueError("Invalid detector response")
                return data, (crop.read_bytes() if crop.is_file() else None)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            logger.warning("detector unavailable, fallback to classifier", exc_info=True)
            return None, None


def _prepare(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported format")
            if source.width * source.height > MAX_PIXELS:
                raise DomainError(413, "PAYLOAD_TOO_LARGE", "图片像素过大，请使用不超过2400万像素的图片")
            converted = ImageOps.exif_transpose(source).convert("RGB")
            converted.thumbnail((2048, 2048))
            output = io.BytesIO()
            converted.save(output, format="JPEG", quality=95)
            return output.getvalue()
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError(415, "UNSUPPORTED_MEDIA", "图片无法解码，请使用完整的JPEG、PNG或WebP图片") from exc


@router.post("/recognitions", response_model=RecognitionOut, tags=["recognition"], summary="识别一张尚未上传的采集图片")
async def recognize(request: Request, image_id: str = Header(alias="X-Image-ID"),
                    _user: dict = Depends(require_roles("collector"))) -> RecognitionOut:
    if not UUID7.fullmatch(image_id):
        raise DomainError(422, "VALIDATION_ERROR", "图片编号必须为UUIDv7")
    if request.headers.get("content-type", "").split(";")[0].lower() not in {"image/jpeg", "image/png", "image/webp"}:
        raise DomainError(415, "UNSUPPORTED_MEDIA", "只接受JPEG、PNG或WebP图片")
    work: UploadWork = request.app.state.recognition_work
    with work.admit():
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise DomainError(413, "PAYLOAD_TOO_LARGE", "单张识别图片不能超过20MiB")
            data.extend(chunk)
        prepared = await work.run(_prepare, bytes(data))
        # 先用检测器判断画面里有没有叶片；有则按最大叶片框裁剪后再分类。
        detection, crop = await work.run(request.app.state.detector.detect, prepared)
        if detection is not None and not detection.get("leaf_detected"):
            raise DomainError(422, "NO_LEAF", "画面中没有检测到叶片主体，请靠近叶片、让叶片占满画面中央后重试")
        raw = await work.run(request.app.state.recognizer.predict, crop or prepared)
        try:
            candidates = [Candidate.model_validate(item) for item in raw["candidates"]]
            with request.app.state.storage.transaction(write=False) as store:
                for candidate in candidates:
                    row = store.get_class(candidate.class_id) if candidate.class_id else None
                    if row is None or not row.get("is_active"):
                        candidate.class_id = None
            return RecognitionOut(image_id=image_id, sha256=hashlib.sha256(data).hexdigest(),
                model=raw["model"], model_version=raw["model_version"], scope=raw["scope"],
                candidates=candidates, warning=raw["warning"], created_at=iso_utc())
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError(503, "MODEL_UNAVAILABLE", "模型返回结果无效，请稍后重试") from exc
