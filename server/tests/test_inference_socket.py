"""常驻推理服务的客户端协议与降级路径（Unix socket，不加载任何模型）。"""
from __future__ import annotations

import base64
import json
import os
import socket
import threading

import pytest

from server.app.recognition import InferenceSocket, SocketClassifier, SocketDetector

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix domain socket 仅在 Linux/macOS 覆盖")

CROP = b"\xff\xd8\xff\xe0crop-bytes"


class _FakeServer(threading.Thread):
    """极简 Unix socket 服务端，按请求 op 返回固定 JSON。"""

    def __init__(self, path: str, responses: dict[str, dict]):
        super().__init__(daemon=True)
        self.path = path
        self.responses = responses
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(4)

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn, conn.makefile("rb") as reader, conn.makefile("wb") as writer:
                line = reader.readline()
                if not line:
                    continue
                request = json.loads(line)
                payload = self.responses.get(request["op"], {"ok": False, "error": "UNKNOWN_OP"})
                writer.write((json.dumps(payload) + "\n").encode())
                writer.flush()

    def stop(self) -> None:
        self.server.close()


def _detect_response() -> dict:
    return {
        "ok": True,
        "detection": {"model": "fake", "version": "1", "leaf_detected": True, "top_leaf": {"label": "leaf"}},
        "crop": base64.b64encode(CROP).decode(),
    }


def _classify_response() -> dict:
    return {
        "ok": True,
        "classification": {"model": "fake", "model_version": "1", "scope": "leaf",
                           "candidates": [{"label": "canker", "name": "溃疡病", "score": 0.9}], "warning": "w"},
    }


class _Recorder:
    """记录是否被调用，用来验证降级路径。"""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def predict(self, image: bytes):
        self.calls += 1
        return self.result

    def detect(self, image: bytes):
        self.calls += 1
        return self.result


def test_socket_classifier_and_detector(tmp_path):
    path = str(tmp_path / "inference.sock")
    server = _FakeServer(path, {
        "detect": _detect_response(),
        "classify": _classify_response(),
        "health": {"ok": True, "ready": True, "classifier": "fake", "detector": "fake"},
    })
    server.start()
    try:
        client = InferenceSocket(path, timeout=5)
        classifier = SocketClassifier(client, _Recorder(None))
        detector = SocketDetector(client, _Recorder((None, None)))

        assert classifier.predict(b"image")["candidates"][0]["label"] == "canker"
        detection, crop = detector.detect(b"image")
        assert detection["leaf_detected"] is True
        assert crop == CROP
        assert client.call("health")["ready"] is True
    finally:
        server.stop()


def test_socket_error_response_raises_domain_error(tmp_path):
    from server.app.common import DomainError

    path = str(tmp_path / "inference.sock")
    server = _FakeServer(path, {"classify": {"ok": False, "error": "INFERENCE_FAILED"}})
    server.start()
    try:
        client = InferenceSocket(path, timeout=5)
        with pytest.raises(DomainError) as excinfo:
            client.call("classify", b"image")
        assert excinfo.value.status_code == 503
    finally:
        server.stop()


def test_classifier_falls_back_when_daemon_missing(tmp_path):
    fallback = _Recorder(_classify_response()["classification"])
    classifier = SocketClassifier(InferenceSocket(str(tmp_path / "absent.sock"), timeout=2), fallback)
    assert classifier.predict(b"image")["model"] == "fake"
    assert fallback.calls == 1


def test_detector_falls_back_when_daemon_missing(tmp_path):
    fallback = _Recorder(({"leaf_detected": False}, None))
    detector = SocketDetector(InferenceSocket(str(tmp_path / "absent.sock"), timeout=2), fallback)
    detection, crop = detector.detect(b"image")
    assert detection["leaf_detected"] is False
    assert crop is None
    assert fallback.calls == 1
