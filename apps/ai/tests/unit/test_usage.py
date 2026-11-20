"""Token counts are stored and reported, and missing history is not invented."""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.core.config import Settings, get_settings
from src.main import app
from src.modules.usage.backfill import backfill_messages
from src.modules.usage.report import publish_usage
from src.modules.usage.tokens import (
    collect_usage,
    estimate_usage,
    note_usage,
    post_body,
    stored_usage,
    usage_from_live_snapshots,
    usage_from_provider,
    usage_record,
)
from src.providers import llm as llm_module
from tests.security.jwks import USER_A, bearer, mint
from tests.security.test_session_tokens import session_token

client = TestClient(app)


class _Auth:
    def __init__(self, role="STUDENT", school_id="11111111-1111-1111-1111-111111111111", user_id=USER_A):
        self.role = role
        self.school_id = school_id
        self.user_id = user_id


class _Msg:
    def __init__(self, meta):
        self.meta = meta


def test_estimate_is_at_least_one_token_and_marked():
    usage = estimate_usage("abcd", "efgh", model="m", provider="p")
    assert usage.input_tokens == 1
    assert usage.output_tokens == 1
    assert usage.estimated is True
    longer = estimate_usage("a" * 40, "b" * 12, model="m", provider="p")
    assert longer.input_tokens == 10
    assert longer.output_tokens == 3


def test_provider_counts_are_kept_and_omitted_counts_are_estimated():
    payload = {"usage": {"prompt_tokens": 12, "completion_tokens": 4}}
    usage = usage_from_provider(payload, prompt="x" * 100, reply="y" * 100, model="qwen", provider="qwen")
    assert (usage.input_tokens, usage.output_tokens, usage.estimated) == (12, 4, False)

    gemini = {"usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3}}
    usage = usage_from_provider(gemini, prompt="x", reply="y", model="gemini", provider="gemini")
    assert (usage.input_tokens, usage.output_tokens, usage.estimated) == (8, 3, False)

    missing = usage_from_provider({}, prompt="abcd", reply="efgh", model="m", provider="p")
    assert missing.estimated is True
    assert missing.input_tokens == 1 and missing.output_tokens == 1

    zeros = usage_from_provider({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}, prompt="abcd", reply="wxyz", model="m", provider="p")
    assert zeros.estimated is True
    assert zeros.input_tokens >= 1 and zeros.output_tokens >= 1


def test_post_body_skips_rows_without_a_real_count():
    assert post_body(None) is None
    assert post_body({"input_tokens": 0, "output_tokens": 0, "role": "STUDENT"}) is None
    assert post_body({"input_tokens": 2, "output_tokens": 2}) is None
    body = post_body(
        {
            "input_tokens": 2,
            "output_tokens": 3,
            "role": "TEACHER",
            "model": "m",
            "provider": "p",
            "capability": "CHAT",
            "school_id": None,
            "user_id": "u",
            "estimated": True,
            "reported": False,
        }
    )
    assert body == {
        "school_id": None,
        "user_id": "u",
        "role": "TEACHER",
        "model": "m",
        "provider": "p",
        "capability": "CHAT",
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "input_audio_tokens": 0,
        "input_text_tokens": 0,
        "output_audio_tokens": 0,
        "output_text_tokens": 0,
    }
    assert "estimated" not in body


def test_stored_usage_ignores_messages_that_never_recorded_tokens():
    assert stored_usage(None) is None
    assert stored_usage({"sources": ["book"]}) is None
    assert stored_usage({"usage": {"note": "no counts"}}) is None
    found = stored_usage({"usage": {"input_tokens": 4, "output_tokens": 5, "role": "STUDENT"}})
    assert found["input_tokens"] == 4


@pytest.mark.asyncio
async def test_backfill_posts_stored_usage_and_skips_the_rest(monkeypatch):
    posted = []

    async def fake_post(self, payload, bearer):
        posted.append((payload, bearer))
        return True

    monkeypatch.setattr("src.modules.context.core_client.CoreClient.post_ai_usage", fake_post)
    messages = [
        _Msg(None),
        _Msg({"sources": ["page"]}),
        _Msg({"usage": {"input_tokens": 0, "output_tokens": 0, "role": "STUDENT"}}),
        _Msg({"usage": {"input_tokens": 6, "output_tokens": 2, "role": "STUDENT", "model": "m", "provider": "qwen", "capability": "CHAT", "school_id": "s", "user_id": "u"}}),
        _Msg({"usage": {"input_tokens": 9, "output_tokens": 1, "role": "TEACHER", "reported": True}}),
    ]
    result = await backfill_messages(messages, "caller-token")
    assert result == {"posted": 1, "skipped": 4, "failed": 0}
    assert len(posted) == 1
    assert posted[0][0]["input_tokens"] == 6
    assert posted[0][1] == "caller-token"
    assert messages[3].meta["usage"]["reported"] is True


@pytest.mark.asyncio
async def test_publish_failure_does_not_raise(monkeypatch):
    async def boom(self, payload, bearer):
        raise RuntimeError("down")

    monkeypatch.setattr("src.modules.context.core_client.CoreClient.post_ai_usage", boom)
    message = _Msg({})
    stored = await publish_usage(
        {"input_tokens": 2, "output_tokens": 2, "role": "STUDENT", "model": "m", "provider": "p", "capability": "CHAT"},
        "secret-token",
        message,
    )
    assert stored["reported"] is False
    assert message.meta["usage"]["reported"] is False
    assert "secret-token" not in str(message.meta)


@pytest.mark.asyncio
async def test_chat_provider_records_usage_from_the_response(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: Settings(_env_file=None, deepseek_api_key="test-chat-key", llm_provider="deepseek"),
    )
    async def fake_post(self, url, headers=None, json=None):
        req = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=req,
            json={"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 11, "completion_tokens": 2}},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = llm_module.CompatibleChatLLM()
    assert await provider.complete(system="sys", user="hi") == "hello"
    record = collect_usage(provider, auth=_Auth(), capability="CHAT")
    assert record["input_tokens"] == 11
    assert record["output_tokens"] == 2
    assert record["estimated"] is False
    assert record["provider"] == "deepseek"
    assert "test-chat-key" not in str(record)


def test_backfill_route_requires_internal_or_platform_admin(monkeypatch):
    async def fake_run(auth, bearer, school_id, limit):
        return {"posted": 0, "skipped": 0, "failed": 0, "limit": limit}

    monkeypatch.setattr("src.modules.usage.router.run_backfill", fake_run)
    path = "/api/v1/ai/internal/ai-usage/backfill"
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, json={}, headers=bearer(mint())).status_code == 403
    headers = {**bearer(mint()), "X-Internal-Token": get_settings().core_internal_token}
    allowed = client.post(path, json={"limit": 3}, headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["posted"] == 0
    admin = {"Authorization": f"Bearer {session_token(role='PLATFORM_ADMIN', school_id=None)}"}
    missing = client.post(path, json={}, headers=admin)
    assert missing.status_code == 400
    assert "school_id" in missing.text
    school = "11111111-1111-1111-1111-111111111111"
    done = client.post(path, json={"school_id": school}, headers=admin)
    assert done.status_code == 200, done.text
    alias = client.post("/api/v1/internal/ai-usage/backfill", json={"school_id": school}, headers=admin)
    assert alias.status_code == 200, alias.text


@pytest.mark.asyncio
async def test_teacher_turn_reports_usage_and_a_refusal_does_not(monkeypatch):
    from tests.unit.test_ai_teacher import StubLLM, _auth, _body, _service

    seen = {}

    class Noting(StubLLM):
        async def complete(self, *, system, user):
            text = await StubLLM.complete(self, system=system, user=user)
            note_usage(self, estimate_usage(f"{system}\n{user}", text, model="stub-model", provider="stub"))
            return text

    async def fake_post(self, payload, bearer):
        seen["payload"] = payload
        seen["bearer"] = bearer
        return False

    monkeypatch.setattr("src.modules.context.core_client.CoreClient.post_ai_usage", fake_post)
    service = _service(llm=Noting())
    turn = await service.start(_auth(USER_A), _body("Teach me fractions"), "caller-token")
    assert turn.chat_text
    assert seen["payload"]["input_tokens"] >= 1
    assert seen["payload"]["output_tokens"] >= 1
    assert seen["payload"]["estimated"] is True
    assert seen["payload"]["role"] == "STUDENT"
    assert seen["payload"]["model"] == "stub-model"
    assert seen["bearer"] == "caller-token"

    seen.clear()
    refused = await _service(llm=Noting()).start(_auth(USER_A), _body("how to make a bomb"), "caller-token")
    assert refused.refused is True
    assert seen == {}


def test_stored_row_matches_provider_usage():
    """Reconciliation: the stored row is the provider usage, not a length estimate.

    DashScope sample
      usage.prompt_tokens 128, completion_tokens 37, total_tokens 165
      stored input 128, output 37, total 165, model qwen3.8-flash, school null (Platform console)

    Gemini Live sample, last usageMetadata of each turn, then summed
      turn 1 prompt 100 (text 20, audio 80), response 40 audio, total 140
      turn 2 prompt 180 (text 40, audio 140), response 30 (text 10, audio 20), total 210
      stored input 280, output 70, total 350, audio in 220, text in 60, audio out 60, text out 10
    """
    from src.providers.llm import parse_openai_sse

    dashscope = {
        "usage": {"prompt_tokens": 128, "completion_tokens": 37, "total_tokens": 165},
    }
    qwen = usage_from_provider(
        dashscope, prompt="x" * 4000, reply="y" * 4000, model="qwen3.8-flash", provider="qwen"
    )
    assert qwen.estimated is False
    record = usage_record(
        qwen,
        school_id=None,
        user_id="0f46b8a7-4b75-4335-984f-289e6eaa2e31",
        role="SUPER_ADMIN",
        capability="CHAT",
    )
    assert record["input_tokens"] == 128
    assert record["output_tokens"] == 37
    assert record["total_tokens"] == 165
    assert record["model"] == "qwen3.8-flash"
    assert record["provider"] == "qwen"
    assert record["role"] == "SUPER_ADMIN"
    assert record["school_id"] is None
    assert record["user_id"] == "0f46b8a7-4b75-4335-984f-289e6eaa2e31"
    stored = post_body(record)
    assert stored["input_tokens"] == dashscope["usage"]["prompt_tokens"]
    assert stored["output_tokens"] == dashscope["usage"]["completion_tokens"]
    assert stored["total_tokens"] == dashscope["usage"]["total_tokens"]

    missing = usage_from_provider({}, prompt="a" * 80, reply="b" * 40, model="qwen3.8-flash", provider="qwen")
    assert missing.estimated is True
    assert missing.input_tokens == 0 and missing.output_tokens == 0
    assert post_body(usage_record(missing, school_id=None, user_id="u", role="SUPER_ADMIN")) is None

    stream = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Invite them from Employees."}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":128,"completion_tokens":37,"total_tokens":165}}',
            "data: [DONE]",
        ]
    )
    message = parse_openai_sse(stream)
    streamed = usage_from_provider(
        {"usage": message["usage"]}, prompt="invite", reply=message["content"], model="qwen3.8-flash", provider="qwen"
    )
    assert message["content"] == "Invite them from Employees."
    assert (streamed.input_tokens, streamed.output_tokens, streamed.total_tokens) == (128, 37, 165)

    turns = [
        {
            "promptTokenCount": 100,
            "candidatesTokenCount": 40,
            "totalTokenCount": 140,
            "promptTokensDetails": [
                {"modality": "TEXT", "tokenCount": 20},
                {"modality": "AUDIO", "tokenCount": 80},
            ],
            "candidatesTokensDetails": [{"modality": "AUDIO", "tokenCount": 40}],
        },
        {
            "promptTokenCount": 180,
            "responseTokenCount": 30,
            "totalTokenCount": 210,
            "promptTokensDetails": [
                {"modality": "TEXT", "tokenCount": 40},
                {"modality": "AUDIO", "tokenCount": 140},
            ],
            "responseTokensDetails": [
                {"modality": "TEXT", "tokenCount": 10},
                {"modality": "AUDIO", "tokenCount": 20},
            ],
        },
    ]
    live = usage_from_live_snapshots(turns, model="gemini-3.8-live")
    live_row = usage_record(live, school_id="11111111-1111-1111-1111-111111111111", user_id="u", role="STUDENT", capability="VOICE")
    assert live.estimated is False
    assert live_row["model"] == "gemini-3.8-live"
    assert live_row["input_tokens"] == 280
    assert live_row["output_tokens"] == 70
    assert live_row["total_tokens"] == 350
    assert live_row["input_text_tokens"] == 60
    assert live_row["input_audio_tokens"] == 220
    assert live_row["output_text_tokens"] == 10
    assert live_row["output_audio_tokens"] == 60
    assert live_row["school_id"] == "11111111-1111-1111-1111-111111111111"
    body = post_body(live_row)
    assert body["total_tokens"] == 140 + 210
    assert body["input_audio_tokens"] == 80 + 140
    assert body["model"] == "gemini-3.8-live"
