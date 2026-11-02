"""CLI 单图分类（兼容旧接口）；实现见 model_runtime。"""
import argparse
import json
from pathlib import Path

from model_runtime import Classifier


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    classifier = Classifier.load(args.manifest)
    result = classifier.predict_bytes(Path(args.image).read_bytes())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
