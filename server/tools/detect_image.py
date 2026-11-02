"""CLI 叶片检测（兼容旧接口）；实现见 model_runtime。"""
import argparse
import json
from pathlib import Path

from model_runtime import Detector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--crop-out", default="")
    args = parser.parse_args()
    detector = Detector.load(args.manifest)
    summary, crop = detector.detect_bytes(Path(args.image).read_bytes())
    if crop and args.crop_out:
        Path(args.crop_out).write_bytes(crop)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
