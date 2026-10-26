import hashlib
import io
import threading
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from PIL import Image

from server.app.main import create_app
from server.app.common import new_uuid7


class Classifier:
    def __init__(self):
        self.calls = []

    def predict(self, data):
        self.calls.append(data)
        return {"model": "test-leaf", "model_version": "test-v1", "scope": "leaf", "warning": "test only",
                "candidates": [{"label": "canker", "name": "溃疡病", "score": .8, "class_id": "citrus_canker"},
                               {"label": "other", "name": "未收录类别", "score": .2, "class_id": "missing"}]}


def token(client, user="collector1"):
    return {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"username": user, "password": "12345678"}).json()["access_token"]}


def png():
    output = io.BytesIO()
    Image.new("RGB", (20, 30), "green").save(output, format="PNG")
    return output.getvalue()


def test_single_recognition_is_authenticated_validated_and_does_not_create_samples():
    classifier = Classifier()
    with TestClient(create_app("memory", recognizer=classifier)) as client:
        data = png()
        image_id = new_uuid7()
        headers = {"Content-Type": "image/png", "X-Image-ID": image_id}
        assert client.post("/api/v1/recognitions", headers=headers, content=data).status_code == 401
        assert client.post("/api/v1/recognitions", headers={**headers, **token(client, "admin")}, content=data).status_code == 403
        headers.update(token(client))
        assert client.post("/api/v1/recognitions", headers={**headers, "X-Image-ID": "bad"}, content=data).status_code == 422
        assert client.post("/api/v1/recognitions", headers=headers, content=b"not a PNG").status_code == 415
        assert client.post("/api/v1/recognitions", headers={**headers, "Content-Type": "application/json"}, content=data).status_code == 415
        assert not classifier.calls
        response = client.post("/api/v1/recognitions", headers=headers, content=data)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["image_id"] == image_id and result["sha256"] == hashlib.sha256(data).hexdigest()
        assert result["candidates"][0]["class_id"] == "citrus_canker"
        assert result["candidates"][1]["class_id"] is None
        assert classifier.calls[0].startswith(b"\xff\xd8")
        assert client.get("/api/v1/samples", headers=headers).json()["total"] == 0


def test_unconfigured_or_invalid_classifier_never_returns_fake_predictions(monkeypatch):
    monkeypatch.delenv("APP_RECOGNITION_PYTHON", raising=False)
    monkeypatch.delenv("APP_RECOGNITION_MANIFEST", raising=False)
    with TestClient(create_app("memory")) as client:
        response = client.post("/api/v1/recognitions", headers={**token(client), "Content-Type": "image/png", "X-Image-ID": new_uuid7()}, content=png())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    invalid = Classifier()
    invalid.predict = lambda _: {"candidates": [{"label": "x", "name": "x", "score": float("nan")} ]}
    with TestClient(create_app("memory", recognizer=invalid)) as client:
        response = client.post("/api/v1/recognitions", headers={**token(client), "Content-Type": "image/png", "X-Image-ID": new_uuid7()}, content=png())
        assert response.status_code == 503


def test_recognition_admits_only_one_model_process():
    classifier = Classifier()
    entered, release = threading.Event(), threading.Event()
    original = classifier.predict
    def slow(data):
        entered.set()
        assert release.wait(5)
        return original(data)
    classifier.predict = slow
    with TestClient(create_app("memory", recognizer=classifier)) as client, ThreadPoolExecutor(max_workers=1) as pool:
        headers = {**token(client), "Content-Type": "image/png", "X-Image-ID": new_uuid7()}
        future = pool.submit(client.post, "/api/v1/recognitions", headers=headers, content=png())
        try:
            assert entered.wait(3)
            assert client.post("/api/v1/recognitions", headers=headers, content=png()).status_code == 429
        finally:
            release.set()
        assert future.result().status_code == 200


def test_configured_classifier_uses_existing_worker_and_cleans_temporary_image(tmp_path, monkeypatch):
    from server.app.recognition import LocalClassifier
    import json
    monkeypatch.setenv("APP_RECOGNITION_PYTHON", __import__("sys").executable)
    manifest = tmp_path / "model.json"
    manifest.write_text("{}")
    monkeypatch.setenv("APP_RECOGNITION_MANIFEST", str(manifest))
    images = []
    def run(command, **kwargs):
        assert Path(command[1]).is_file()
        assert Path(command[1]).parent.name == "tools"
        image = Path(command[-1])
        assert image.read_bytes() == b"prepared image"
        images.append(image)
        return SimpleNamespace(returncode=0, stdout=json.dumps(Classifier().predict(b"")))
    monkeypatch.setattr("server.app.recognition.subprocess.run", run)
    assert LocalClassifier(tmp_path).predict(b"prepared image")["model"] == "test-leaf"
    assert not images[0].exists()
