"""Platform console assistant stays on the real pages and does not invent controls."""

import json

from fastapi.testclient import TestClient

from src.main import app
from src.modules.platform_assistant.prompt import PLATFORM_ROUTES, PLATFORM_SYSTEM, PLATFORM_TOOL_NOTE, plain_markdown
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
    assert SYSTEM.startswith(PLATFORM_SYSTEM)
    assert "calling tools" in PLATFORM_TOOL_NOTE.lower()
    assert "do not say you cannot create records" in PLATFORM_TOOL_NOTE.lower()
    voice = build_system_prompt("", None, "/platform/admins", "platform")
    assert "Add student" not in voice
    assert "/platform/settings" in voice
    assert "Password & Security" in voice


def test_platform_chat_strips_decorative_asterisks(monkeypatch):
    async def fake_step(**kwargs):
        assert "/platform/schools" in kwargs["system_override"]
        assert "Invite User" not in kwargs["system_override"]
        assert "do not say you cannot create records" in kwargs["system_override"].lower()
        return {
            "message": {
                "role": "assistant",
                "content": "**Create the School**\n\nGo to **Schools** > **Add New School**.",
            },
            "provider": "test",
            "model": "test",
        }

    monkeypatch.setattr("src.modules.platform_assistant.router.agent.agent_step", fake_step)
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


def test_platform_chat_returns_the_write_tool_for_the_card(monkeypatch):
    async def fake_step(**kwargs):
        names = [tool["name"] for tool in kwargs["declarations"]]
        assert "invite_employee" in names
        return {
            "message": {
                "role": "assistant",
                "content": "Add this employee.",
                "tool_calls": [_call("invite_employee", {"full_name": "Ada", "email": "ada@example.com"})],
            },
            "provider": "qwen",
            "model": "qwen3.8-flash",
        }

    monkeypatch.setattr("src.modules.platform_assistant.router.agent.agent_step", fake_step)
    response = client.post(
        "/api/v1/ai/platform-assistant/chat",
        json={
            "message": "add one employee named Ada at ada@example.com",
            "page": "/platform/staff",
            "tools": [{"name": "invite_employee", "description": "Invite an employee", "parameters": {}}],
        },
        headers=_headers(role="PLATFORM_ADMIN", school_id=None),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmation_required"] is True
    assert body["executed"] is False
    assert body["message"]["tool_calls"][0]["function"]["name"] == "invite_employee"


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


def test_write_tool_is_returned_for_the_confirmation_card():
    result = apply_platform_tool_policy({
        "message": {
            "role": "assistant",
            "content": "Add **Ada**.",
            "tool_calls": [_call("invite_employee", {"full_name": "Ada", "email": "ada@example.com"})],
        },
        "provider": "test",
        "model": "test",
    })
    assert result["confirmation_required"] is True
    assert result["executed"] is False
    call = result["message"]["tool_calls"][0]
    assert call["function"]["name"] == "invite_employee"
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
    assert body["message"]["tool_calls"][0]["function"]["name"] == "type_in_element"
    declared = [tool["name"] for tool in seen["declarations"]]
    assert "list_platform_pages" in declared
    assert "open_platform_page" in declared
    assert "/platform/schools" in seen["system_override"]
    assert "Invite User" not in seen["system_override"]
    assert "not a valid route" not in seen["system_override"].lower()


def test_profile_trailing_slash_is_accepted_and_prompt_does_not_call_the_url_invalid():
    """`/platform/profile/` is the signed-in person's profile, not an invalid URL."""
    assert canonical_platform_route("/platform/profile/") == "/platform/profile"
    assert canonical_platform_route("/platform/profile") == "/platform/profile"
    assert canonical_platform_route("profile") == "/platform/profile"
    assert canonical_platform_route("/platform/settings/") == "/platform/settings"
    assert canonical_platform_route("/platform/attention/") == "/platform/attention"
    assert canonical_platform_route("/platform/schools/{id}") is None
    assert canonical_platform_route("/platform/schools/:id") is None
    routes = dict(PLATFORM_ROUTES)
    assert "Team" not in routes
    assert routes["Employees"] == "/platform/staff"
    assert "/platform/team" not in PLATFORM_SYSTEM
    assert canonical_platform_route("/platform/team") == "/platform/staff"
    assert canonical_platform_route("team") == "/platform/staff"
    assert routes["Profile"] == "/platform/profile"
    assert routes["Settings"] == "/platform/settings"
    assert routes["Attention"] == "/platform/attention"
    assert routes["School detail"] == "/platform/schools/{id}"

    lowered = PLATFORM_SYSTEM.lower()
    assert "/platform/profile" in PLATFORM_SYSTEM
    assert "name, email, and role" in lowered
    assert "it is not settings" in lowered
    assert "do not comment on the current url" in lowered
    assert "do not say a route is invalid" in lowered
    for phrase in (
        "not a valid route",
        "invalid route",
        "url is invalid",
        "url is not valid",
        "current url is not",
    ):
        assert phrase not in lowered

    voice = build_system_prompt("", None, "/platform/profile/", "platform")
    voice_lower = voice.lower()
    assert "not a valid route" not in voice_lower
    assert "invalid route" not in voice_lower
    assert "Current page: /platform/profile." in voice
    assert "Current page: /platform/profile/" not in voice
    assert "{id}" not in voice
    assert ":id" not in voice

    result = apply_platform_tool_policy({
        "message": {
            "role": "assistant",
            "content": "The school is at /platform/schools/{id}.",
            "tool_calls": [_call("open_platform_page", {"page": "/platform/profile/"})],
        },
        "provider": "test",
        "model": "test",
    })
    call = result["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"page": "/platform/profile"}
    assert "{id}" not in result["message"]["content"]
    assert ":id" not in result["message"]["content"]
    assert "/platform/schools" in result["message"]["content"]
    assert "{id}" not in plain_markdown("Open /platform/schools/:id for the record.")
    assert "Schools (/platform/schools)" in plain_markdown("Open /platform/schools/:id for the record.")
