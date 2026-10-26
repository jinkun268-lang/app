"""Bounded CPU inference using a configured local torchvision state_dict; no downloads."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    import torch
    from torchvision import models, transforms
    from PIL import Image
    torch.set_num_threads(2)
    labels = config["classes"]
    if config["architecture"] != "efficientnet_b0" or not 2 <= len(labels) <= 100:
        raise ValueError("Unsupported model configuration")
    weights = Path(config["weights"])
    model = models.efficientnet_b0(weights=None)
    model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(labels))
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True), strict=True)
    model.eval()
    transform = transforms.Compose([transforms.Resize(255), transforms.CenterCrop(224), transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    with Image.open(args.image) as image:
        tensor = transform(image.convert("RGB")).unsqueeze(0)
    with torch.inference_mode():
        probabilities = model(tensor).softmax(dim=1)[0]
    top = probabilities.topk(min(3, len(labels)))
    candidates = [{**labels[index], "score": float(score)} for score, index in zip(top.values.tolist(), top.indices.tolist())]
    digest = hashlib.sha256()
    with weights.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    print(json.dumps({"model": config["name"], "model_version": digest.hexdigest()[:16], "scope": "leaf",
        "candidates": candidates, "warning": "实验性叶片五分类模型，仅供人工复核；不适用于果实、虫体，田间泛化尚未验证。"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
