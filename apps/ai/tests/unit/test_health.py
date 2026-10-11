from fastapi.testclient import TestClient

from src.main import app


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    prefixed = client.get("/api/v1/ai/health")
    assert prefixed.status_code == 200
    assert prefixed.json()["status"] == "ok"


def test_chat_requires_auth():
    client = TestClient(app)
    r = client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert r.status_code == 401
