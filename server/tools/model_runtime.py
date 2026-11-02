"""模型加载与推理的唯一实现：CLI 脚本与常驻推理服务共用，避免逻辑分叉。

只依赖 torch/torchvision/ultralytics/Pillow，不依赖应用包，可由 model-venv 直接运行。
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

CLASSIFIER_WARNING = "实验性叶片五分类模型，仅供人工复核；不适用于果实、虫体，田间泛化尚未验证。"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(manifest: str | Path) -> dict:
    return json.loads(Path(manifest).read_text(encoding="utf-8"))


class Classifier:
    """torchvision EfficientNet-B0 五分类；权重只从本地读取，不下载预训练权重。"""

    def __init__(self, config: dict, threads: int = 2):
        import torch
        from torchvision import models, transforms

        torch.set_num_threads(threads)
        labels = config["classes"]
        if config.get("architecture") != "efficientnet_b0" or not 2 <= len(labels) <= 100:
            raise ValueError("Unsupported model configuration")
        weights = Path(config["weights"])
        if not weights.is_file():
            raise ValueError("Missing classifier weights")
        model = models.efficientnet_b0(weights=None)
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(labels))
        model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True), strict=True)
        model.eval()

        self._torch = torch
        self.model = model
        self.labels = labels
        self.name = config["name"]
        self.version = file_digest(weights)[:16]
        self.transform = transforms.Compose([
            transforms.Resize(255),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    @classmethod
    def load(cls, manifest: str | Path, threads: int = 2) -> "Classifier":
        return cls(read_manifest(manifest), threads=threads)

    def predict_bytes(self, data: bytes) -> dict:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            tensor = self.transform(image.convert("RGB")).unsqueeze(0)
        with self._torch.inference_mode():
            probabilities = self.model(tensor).softmax(dim=1)[0]
        top = probabilities.topk(min(3, len(self.labels)))
        candidates = [
            {**self.labels[index], "score": float(score)}
            for score, index in zip(top.values.tolist(), top.indices.tolist())
        ]
        return {
            "model": self.name,
            "model_version": self.version,
            "scope": "leaf",
            "candidates": candidates,
            "warning": CLASSIFIER_WARNING,
        }


class Detector:
    """YOLO 叶片检测：判断画面有没有叶片，并给出最大叶片框用于裁剪。"""

    def __init__(self, config: dict):
        weights = Path(config["weights"])
        if not weights.is_file():
            raise ValueError("Missing detector weights")
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.names = self.model.names
        self.config = config
        self.name = config.get("name", "leaf detector")
        self.version = file_digest(weights)[:16]
        self.min_score = float(config.get("min_score", 0.25))
        self.max_det = int(config.get("max_det", 30))
        self.leaf_labels = set(config.get("leaf_labels") or [])

    @classmethod
    def load(cls, manifest: str | Path) -> "Detector":
        return cls(read_manifest(manifest))

    def detect_bytes(self, data: bytes) -> tuple[dict, bytes | None]:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGB")
        result = self.model(
            image, conf=self.min_score, max_det=self.max_det, device="cpu", verbose=False
        )[0]
        detections = []
        for cls, score, box in zip(
            result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist()
        ):
            detections.append({
                "label": self.names[int(cls)],
                "score": round(float(score), 4),
                "box": [round(float(value), 1) for value in box],
            })
        leaves = [item for item in detections if item["label"] in self.leaf_labels]
        leaves.sort(
            key=lambda item: (item["box"][2] - item["box"][0]) * (item["box"][3] - item["box"][1]),
            reverse=True,
        )
        crop = self._crop(image, leaves[0]) if leaves else None
        summary = {
            "model": self.name,
            "model_version": self.version,
            "detections": detections,
            "leaf_detected": bool(leaves),
            "top_leaf": leaves[0] if leaves else None,
        }
        return summary, crop

    @staticmethod
    def _crop(image, leaf: dict) -> bytes:
        width, height = image.size
        x1, y1, x2, y2 = leaf["box"]
        pad_x = max(6.0, (x2 - x1) * 0.15)
        pad_y = max(6.0, (y2 - y1) * 0.15)
        box = (
            int(max(0, x1 - pad_x)),
            int(max(0, y1 - pad_y)),
            int(min(width, x2 + pad_x)),
            int(min(height, y2 + pad_y)),
        )
        buffer = io.BytesIO()
        image.crop(box).save(buffer, format="JPEG", quality=95)
        return buffer.getvalue()
