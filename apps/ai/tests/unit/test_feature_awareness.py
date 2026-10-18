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
