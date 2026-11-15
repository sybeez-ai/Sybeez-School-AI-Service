"""Day-one guards: live parent links without the exams module, model fallbacks, daily caps."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.core.budget import allow_model, allow_voice
from src.core.config import get_settings
from src.core.exceptions import UpstreamError
from src.core.rate_limit import limiter
from src.main import app
from src.modules.context.core_client import CoreClient, parse_child_ids, reset_parent_child_cache
from src.modules.context.schemas import AuthorizedLearningContext, CurrentLearning, SchoolContext, StudentContext
from src.modules.evaluation.schemas import EvaluationRequest
from src.modules.evaluation.service import EvaluationService
from src.modules.homework_help import service as homework
from src.modules.profile.router import parent_still_linked
from src.modules.voice import router as voice
from tests.security.jwks import bearer, mint

CHILD = UUID("12345678-1234-5678-1234-567812345678")
client = TestClient(app)


def _transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "src.modules.context.core_client.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_parse_child_ids_accepts_a_list_or_an_envelope():
    raw = str(CHILD)
    assert parse_child_ids([{"student_id": raw}, {"student_id": "not-a-uuid"}, "nope"]) == {CHILD}
    assert parse_child_ids({"data": [{"student_id": raw}]}) == {CHILD}
    assert parse_child_ids({"children": [{"student_id": raw}]}) == {CHILD}
    assert parse_child_ids({"unexpected": []}) == set()


@pytest.mark.asyncio
async def test_parent_links_do_not_depend_on_exams(monkeypatch):
    """Schools with exams switched off must still resolve live children."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/parents/me/children"):
            return httpx.Response(200, json=[{"student_id": str(CHILD), "relationship": "mother"}])
        return httpx.Response(403, json={"error": {"code": "feature_disabled", "message": "Exams are off"}})

    _transport(monkeypatch, handler)
    found = await CoreClient().parent_child_ids(bearer_token="parent-token")
    assert found == {CHILD}
    assert seen == ["/api/v1/parents/me/children"]


@pytest.mark.asyncio
async def test_missing_parents_route_falls_back_to_exams_once(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/parents/me/children"):
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(200, json={"data": [{"student_id": str(CHILD)}]})

    _transport(monkeypatch, handler)
    assert await CoreClient().parent_child_ids(bearer_token="parent-token") == {CHILD}
    assert seen == ["/api/v1/parents/me/children", "/api/v1/exams/parent/children"]


@pytest.mark.asyncio
async def test_parent_portal_off_does_not_fall_through_to_exams(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(403, json={"error": {"code": "feature_disabled"}})

    _transport(monkeypatch, handler)
    assert await CoreClient().parent_child_ids(bearer_token="parent-token") == set()
    assert seen == ["/api/v1/parents/me/children"]


@pytest.mark.asyncio
async def test_parent_link_lookup_caches_success_and_not_failure(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=[{"student_id": str(CHILD)}])

    _transport(monkeypatch, handler)
    client_ = CoreClient()
    assert await client_.parent_child_ids(bearer_token="parent-token") == set()
    assert await client_.parent_child_ids(bearer_token="parent-token") == {CHILD}
    assert await client_.parent_child_ids(bearer_token="parent-token") == {CHILD}
    assert calls["n"] == 2
    reset_parent_child_cache()


@pytest.mark.asyncio
async def test_parent_link_lookup_without_a_token_does_not_call_core(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Core must not be called")

    _transport(monkeypatch, handler)
    assert await CoreClient().parent_child_ids(bearer_token=None) == set()
    assert await CoreClient().parent_child_ids(bearer_token="") == set()


def test_unlinked_parent_profile_is_hidden():
    row = SimpleNamespace(student_id=CHILD)
    assert parent_still_linked(row, {CHILD})
    assert not parent_still_linked(row, set())
    assert not parent_still_linked(SimpleNamespace(student_id=None), {CHILD})
    assert not parent_still_linked(None, {CHILD})


@pytest.mark.asyncio
async def test_homework_model_outage_returns_a_safe_nudge(monkeypatch):
    async def down(*_args, **_kwargs):
        raise UpstreamError("down")

    monkeypatch.setattr(homework, "guarded_complete", down)
    monkeypatch.setattr(homework, "_llm", lambda: object())
    result = await homework.help_student(homework.HelpRequest(question="What is 12 + 3 x 4?"))
    assert result.held_back_answer
    assert "24" not in result.reply
    assert result.reply


@pytest.mark.asyncio
async def test_evaluation_does_not_mark_a_long_answer_correct_when_the_model_is_down():
    service = EvaluationService()

    class Down:
        async def complete(self, *, system, user):
            raise UpstreamError("down")

    class Ctx:
        async def for_user(self, *_args, **_kwargs):
            return AuthorizedLearningContext(
                student=StudentContext(id=uuid4()),
                school=SchoolContext(id=uuid4()),
                current_learning=CurrentLearning(topic="fractions"),
            )

    service.llm = Down()
    service.context = Ctx()
    result = await service.evaluate(
        SimpleNamespace(),
        EvaluationRequest(question_id="q", question="What is a half?", answer="A long attempt " * 5),
    )
    assert result.correct is False
    assert result.score == 0
    assert "try again" in result.feedback.lower()


def test_typed_assistant_names_the_portal_when_the_model_is_down(monkeypatch):
    async def down(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(voice.agent, "text_answer", down)
    student = client.post(
        "/api/v1/ai/voice/agent/text", json={"message": "explain fractions"}, headers=bearer(mint())
    )
    parent = client.post(
        "/api/v1/ai/voice/agent/text",
        json={"message": "how is my child doing"},
        headers=bearer(mint(role="PARENT")),
    )
    assert student.status_code == 200 and "AI teacher" in student.json()["reply"]
    assert parent.status_code == 200
    assert "AI assistant" in parent.json()["reply"] and "AI teacher" not in parent.json()["reply"]


def test_daily_voice_cap_is_a_clear_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_sessions_per_user_per_day", 1)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "server-key")
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if "generativelanguage" not in request.url.host:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"name": "auth_tokens/one"})

    monkeypatch.setattr(voice.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    headers = bearer(mint())
    assert client.post("/api/v1/ai/voice/gemini/session", headers=headers).status_code == 200
    blocked = client.post("/api/v1/ai/voice/gemini/session", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["message"].startswith("Daily AI limit")


def test_unconfigured_voice_does_not_spend_the_daily_cap(monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_sessions_per_user_per_day", 1)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    headers = bearer(mint())
    assert client.post("/api/v1/ai/voice/gemini/session", headers=headers).status_code == 503
    assert client.post("/api/v1/ai/voice/gemini/session", headers=headers).status_code == 503


def test_audit_events_do_not_spend_the_model_budget(monkeypatch):
    monkeypatch.setattr(get_settings(), "model_calls_per_user_per_day", 1)
    event = {"tool": "click_element", "ok": True, "portal": "teacher", "page": "/teacher"}
    headers = bearer(mint(role="TEACHER"))
    assert client.post("/api/v1/ai/voice/agent/audit", json=event, headers=headers).status_code == 202
    assert client.post("/api/v1/ai/voice/agent/audit", json=event, headers=headers).status_code == 202


@pytest.mark.asyncio
async def test_daily_caps_are_per_user_and_per_school(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "model_calls_per_user_per_day", 5)
    monkeypatch.setattr(settings, "model_calls_per_school_per_day", 1)
    monkeypatch.setattr(settings, "voice_sessions_per_user_per_day", 1)
    school = uuid4()
    first = SimpleNamespace(user_id=uuid4(), school_id=school)
    second = SimpleNamespace(user_id=uuid4(), school_id=school)
    limiter.reset()
    assert await allow_model(first) is True
    assert await allow_model(second) is False
    assert await allow_voice(first) is True
    assert await allow_voice(first) is False
    platform = SimpleNamespace(user_id=uuid4(), school_id=None)
    assert await allow_model(platform) is True
