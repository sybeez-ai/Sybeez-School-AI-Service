from fastapi.testclient import TestClient

from src.main import app
from src.modules.translate import router as tr
from tests.security.jwks import bearer, mint

client = TestClient(app)


class FakeLLM:
    calls = 0

    async def complete(self, *, system, user, **kw):
        FakeLLM.calls += 1
        import json
        return json.dumps([f"hi:{t}" for t in json.loads(user)], ensure_ascii=False)


def test_parent_only_and_validation():
    body = {"lang": "hi", "texts": ["Home"]}
    assert client.post("/api/v1/ai/translate", json=body).status_code == 401
    assert client.post("/api/v1/ai/translate", json=body, headers=bearer(mint())).status_code == 403
    parent = bearer(mint(role="PARENT"))
    assert client.post("/api/v1/ai/translate", json={"lang": "xx", "texts": ["a"]}, headers=parent).status_code == 400


def test_translates_and_caches(monkeypatch):
    monkeypatch.setattr(tr, "get_llm", lambda: FakeLLM())
    tr._CACHE.clear()
    FakeLLM.calls = 0
    parent = bearer(mint(role="PARENT"))
    r = client.post("/api/v1/ai/translate", json={"lang": "ta", "texts": ["Home", "Fees", "Home"]}, headers=parent)
    assert r.status_code == 200 and r.json()["texts"] == ["hi:Home", "hi:Fees", "hi:Home"]
    client.post("/api/v1/ai/translate", json={"lang": "ta", "texts": ["Home"]}, headers=parent)
    assert FakeLLM.calls == 1


def test_bad_model_output_keeps_english(monkeypatch):
    class Bad:
        async def complete(self, **kw):
            return "not json"

    monkeypatch.setattr(tr, "get_llm", lambda: Bad())
    tr._CACHE.clear()
    r = client.post("/api/v1/ai/translate", json={"lang": "hi", "texts": ["Zzz"]}, headers=bearer(mint(role="PARENT")))
    assert r.status_code == 502
