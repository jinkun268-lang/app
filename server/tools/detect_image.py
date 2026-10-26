"""Bounded YOLO detection for the recognition gate; local checkpoint only, no downloads."""
import argparse
import hashlib
import json
from pathlib import Path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--crop-out", default="")
    args = parser.parse_args()
    config = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    weights = Path(config["weights"])
    if not weights.is_file():
        raise ValueError("Missing detector weights")
    from ultralytics import YOLO

    model = YOLO(str(weights))
    result = model(
        args.image,
        conf=float(config.get("min_score", 0.25)),
        max_det=int(config.get("max_det", 30)),
        device="cpu",
        verbose=False,
    )[0]
    names = model.names
    detections = []
    for cls, score, box in zip(
        result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist()
    ):
        label = names[int(cls)]
        detections.append(
            {
                "label": label,
                "score": round(float(score), 4),
                "box": [round(float(value), 1) for value in box],
            }
        )
    leaf_labels = set(config.get("leaf_labels") or [])
    leaves = [item for item in detections if item["label"] in leaf_labels]
    leaves.sort(
        key=lambda item: (item["box"][2] - item["box"][0]) * (item["box"][3] - item["box"][1]),
        reverse=True,
    )
    if leaves and args.crop_out:
        from PIL import Image

        with Image.open(args.image) as image:
            width, height = image.size
            x1, y1, x2, y2 = leaves[0]["box"]
            pad_x = max(6.0, (x2 - x1) * 0.15)
            pad_y = max(6.0, (y2 - y1) * 0.15)
            crop = image.convert("RGB").crop(
                (
                    int(max(0, x1 - pad_x)),
                    int(max(0, y1 - pad_y)),
                    int(min(width, x2 + pad_x)),
                    int(min(height, y2 + pad_y)),
                )
            )
            crop.save(args.crop_out, format="JPEG", quality=95)
    print(
        json.dumps(
            {
                "model": config.get("name", "leaf detector"),
                "model_version": _digest(weights),
                "detections": detections,
                "leaf_detected": bool(leaves),
                "top_leaf": leaves[0] if leaves else None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
