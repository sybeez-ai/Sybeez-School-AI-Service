import asyncio

from src.modules.context import features as F


def test_prompt_block_lists_switched_off_features():
    assert F.prompt_block([]) == ""
    b = F.prompt_block(["Online tests", "Fees", "Fees"])
    assert "Fees, Online tests" in b and "turned them off" in b


def test_fails_open_without_token_and_on_error(monkeypatch):
    assert asyncio.run(F.disabled_labels(None)) == []

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): raise RuntimeError("down")
        async def __aexit__(self, *a): ...

    monkeypatch.setattr(F.httpx, "AsyncClient", Boom)
    assert asyncio.run(F.disabled_labels("tok")) == []


def test_reads_only_disabled(monkeypatch):
    class R:
        status_code = 200
        def json(self): return [{"label": "Fees", "enabled": False}, {"label": "Homework", "enabled": True}]

    class C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, *a, **k): return R()

    monkeypatch.setattr(F.httpx, "AsyncClient", C)
    assert asyncio.run(F.disabled_labels("tok")) == ["Fees"]


def test_ai_switch_blocks_when_core_says_off(monkeypatch):
    class R:
        status_code = 200
        def json(self): return [{"key": "ai_assistant", "label": "AI assistant and AI tools", "enabled": False}]

    class C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, *a, **k): return R()

    F._cache.clear()
    monkeypatch.setattr(F.httpx, "AsyncClient", C)
    assert asyncio.run(F.ai_switched_off("tok-off")) == "AI assistant and AI tools"
    assert asyncio.run(F.ai_switched_off(None)) is None


def test_ai_switch_open_when_on_or_core_down(monkeypatch):
    class R:
        status_code = 200
        def json(self): return [{"key": "ai_assistant", "label": "AI", "enabled": True}]

    class C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, *a, **k): return R()

    F._cache.clear()
    monkeypatch.setattr(F.httpx, "AsyncClient", C)
    assert asyncio.run(F.ai_switched_off("tok-on")) is None

    class Boom(C):
        async def __aenter__(self): raise RuntimeError("down")

    F._cache.clear()
    monkeypatch.setattr(F.httpx, "AsyncClient", Boom)
    assert asyncio.run(F.ai_switched_off("tok-x")) is None


def test_gate_raises_403_feature_disabled(monkeypatch):
    from types import SimpleNamespace

    import pytest

    from src.api import router as R
    from src.core.exceptions import ForbiddenError

    async def off(_):
        return "AI assistant and AI tools"

    monkeypatch.setattr(F, "ai_switched_off", off)
    req = SimpleNamespace(state=SimpleNamespace(token="t"))
    with pytest.raises(ForbiddenError) as e:
        asyncio.run(R.ai_feature_gate(req))
    assert e.value.status_code == 403 and e.value.code == "feature_disabled"
