"""常驻推理服务：模型只加载一次，通过 Unix socket 提供叶片检测与分类。

协议：每条请求/响应一行 UTF-8 JSON，图片用 base64 传输。
    {"op": "health"}                       -> {"ok": true, "ready": true, ...}
    {"op": "detect", "image": "<base64>"}   -> {"ok": true, "detection": {...}, "crop": "<base64>|''"}
    {"op": "classify", "image": "<base64>"} -> {"ok": true, "classification": {...}}
单线程串行处理：CPU 推理在 2 核机器上与并发无益，排队比抢占更快。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import socket
import sys
import time
import traceback

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def log(message: str) -> None:
    print(f"[inference] {message}", file=sys.stderr, flush=True)


def _warmup(classifier, detector) -> None:
    """预热：把首次调用的分配/算子编译成本提前付掉。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (128, 128, 128)).save(buffer, format="JPEG")
    sample = buffer.getvalue()
    started = time.monotonic()
    if detector is not None:
        detector.detect_bytes(sample)
    if classifier is not None:
        classifier.predict_bytes(sample)
    log(f"预热完成（{time.monotonic() - started:.2f}s）")


def _handle(conn: socket.socket, classifier, detector) -> None:
    with conn.makefile("rb") as reader, conn.makefile("wb") as writer:
        line = reader.readline()
        if not line:
            return
        try:
            request = json.loads(line)
        except ValueError:
            payload = {"ok": False, "error": "BAD_REQUEST"}
        else:
            payload = _dispatch(request, classifier, detector)
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        writer.flush()


def _dispatch(request: dict, classifier, detector) -> dict:
    op = request.get("op")
    if op == "health":
        return {
            "ok": True,
            "ready": True,
            "classifier": None if classifier is None else classifier.name,
            "detector": None if detector is None else detector.name,
            "pid": os.getpid(),
        }
    if op not in ("detect", "classify"):
        return {"ok": False, "error": "UNKNOWN_OP"}
    try:
        data = base64.b64decode(request.get("image") or "", validate=True)
    except Exception:
        return {"ok": False, "error": "BAD_IMAGE"}
    if not data:
        return {"ok": False, "error": "BAD_IMAGE"}
    if len(data) > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "PAYLOAD_TOO_LARGE"}
    try:
        if op == "detect":
            if detector is None:
                return {"ok": True, "detection": None, "crop": ""}
            summary, crop = detector.detect_bytes(data)
            return {
                "ok": True,
                "detection": summary,
                "crop": base64.b64encode(crop).decode("ascii") if crop else "",
            }
        if classifier is None:
            return {"ok": False, "error": "MODEL_UNAVAILABLE"}
        return {"ok": True, "classification": classifier.predict_bytes(data)}
    except Exception as exc:  # 单次推理失败不应带走整个服务
        log(f"{op} 失败: {exc}")
        traceback.print_exc()
        return {"ok": False, "error": "INFERENCE_FAILED"}


def serve(socket_path: str, classifier, detector) -> None:
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o600)
    server.listen(16)
    log(f"就绪: {socket_path}")
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    _handle(conn, classifier, detector)
                except (BrokenPipeError, ConnectionResetError):
                    continue
    finally:
        server.close()
        try:
            os.unlink(socket_path)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="常驻推理服务")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--classifier-manifest", default="")
    parser.add_argument("--detector-manifest", default="")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()

    from model_runtime import Classifier, Detector

    classifier = None
    detector = None
    if args.classifier_manifest:
        classifier = Classifier.load(args.classifier_manifest, threads=args.threads)
        log(f"分类模型已加载: {classifier.name} v{classifier.version}")
    if args.detector_manifest:
        detector = Detector.load(args.detector_manifest)
        log(f"检测模型已加载: {detector.name} v{detector.version}")
    if classifier is None and detector is None:
        log("未配置任何模型，服务不会提供推理")
    _warmup(classifier, detector)
    serve(args.socket, classifier, detector)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
