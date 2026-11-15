"""Platform console assistant stays on the real pages and does not invent controls."""

import json

from fastapi.testclient import TestClient

from src.main import app
from src.modules.platform_assistant.prompt import PLATFORM_SYSTEM
from src.modules.platform_assistant.router import SYSTEM
from src.modules.platform_assistant.tools import (
    apply_platform_tool_policy,
    canonical_platform_route,
    with_platform_tools,
)
from src.providers.gemini_live import build_system_prompt
from tests.security.test_session_tokens import session_token

client = TestClient(app)

SCHOOL_ID = "123e4567-e89b-12d3-a456-426614174000"


def _headers(**claims) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(**claims)}"}


def _call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }


def test_platform_prompt_lists_schools_and_does_not_mention_invite_user():
    prompts = (
        PLATFORM_SYSTEM,
        SYSTEM,
        build_system_prompt("", None, "/platform", "platform"),
        build_system_prompt("", None, "/platform/schools", "school-admin"),
    )
    for prompt in prompts:
        assert "/platform/schools" in prompt
        assert "Invite User" not in prompt
    assert SYSTEM == PLATFORM_SYSTEM
    voice = build_system_prompt("", None, "/platform/admins", "platform")
    assert "Add student" not in voice
    assert "/platform/settings" in voice
    assert "Password & Security" in voice


def test_platform_chat_strips_decorative_asterisks(monkeypatch):
    async def fake_complete(llm, *, system, user):
        assert "/platform/schools" in system
        assert "Invite User" not in system
        return "**Create the School**\n\nGo to **Schools** > **Add New School**."

    monkeypatch.setattr("src.modules.platform_assistant.router.guarded_complete", fake_complete)
    monkeypatch.setattr("src.modules.platform_assistant.router.get_llm", lambda: None)
    response = client.post(
        "/api/v1/ai/platform-assistant/chat",
        json={"message": "How do I add a school?", "page": "/platform"},
        headers=_headers(role="PLATFORM_ADMIN", school_id=None),
    )
    assert response.status_code == 200, response.text
    reply = response.json()["reply"]
    assert "**" not in reply
    assert "*" not in reply
    assert "Create the School" in reply
    assert "Schools" in reply


def test_platform_read_tools_point_at_console_routes():
    tools = with_platform_tools([{"name": "click_element", "description": "click", "parameters": {}}])
    names = [tool["name"] for tool in tools]
    assert names[:2] == ["list_platform_pages", "open_platform_page"]
    description = tools[1]["description"]
    assert "/platform/schools" in description
    assert "Invite User" not in description
    assert canonical_platform_route("Schools") == "/platform/schools"
    assert canonical_platform_route(f"/platform/schools/{SCHOOL_ID}") == f"/platform/schools/{SCHOOL_ID}"
    assert canonical_platform_route("/platform/schools/new") is None
    assert canonical_platform_route("users") is None


def test_write_tool_requires_confirmation_and_does_not_execute():
    result = apply_platform_tool_policy({
        "message": {
            "role": "assistant",
            "content": "Click **Invite User**.",
            "tool_calls": [_call("click_element", {"label": "Save"})],
        },
        "provider": "test",
        "model": "test",
    })
    assert result["confirmation_required"] is True
    assert result["executed"] is False
    assert "tool_calls" not in result["message"]
    assert "confirm" in result["message"]["content"].lower()
    assert "**" not in result["message"]["content"]


def test_open_platform_page_navigates_to_the_real_route():
    result = apply_platform_tool_policy({
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("open_platform_page", {"page": "schools"})],
        },
        "provider": "test",
        "model": "test",
    })
    assert result["confirmation_required"] is False
    assert result["executed"] is True
    call = result["message"]["tool_calls"][0]
    assert call["function"]["name"] == "navigate_to_page"
    assert json.loads(call["function"]["arguments"]) == {"page": "/platform/schools"}
    assert "/platform/schools" in result["message"]["content"]


def test_platform_step_offers_read_tools_and_blocks_writes(monkeypatch):
    seen: dict = {}

    async def fake_step(**kwargs):
        seen.update(kwargs)
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("type_in_element", {"text": "secret"})],
            },
            "provider": "test",
            "model": "test",
        }

    monkeypatch.setattr("src.modules.voice.router.agent.agent_step", fake_step)
    response = client.post(
        "/api/v1/ai/voice/agent/step",
        json={
            "messages": [{"role": "user", "content": "Add a school"}],
            "tools": [],
            "portal": "platform",
            "page": "/platform/schools",
        },
        headers=_headers(role="PLATFORM_ADMIN", school_id=None),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmation_required"] is True
    assert body["executed"] is False
    assert "tool_calls" not in body["message"]
    declared = [tool["name"] for tool in seen["declarations"]]
    assert "list_platform_pages" in declared
    assert "open_platform_page" in declared
    assert "/platform/schools" in seen["system_override"]
    assert "Invite User" not in seen["system_override"]
