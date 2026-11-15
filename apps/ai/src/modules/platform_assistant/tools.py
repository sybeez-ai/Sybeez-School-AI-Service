"""Read-only platform tools for the typed agent step.

Reads point at the real console routes. A tool that would change data is not
run; the step returns a confirmation requirement instead.
"""

from __future__ import annotations

import json
import re

from src.modules.platform_assistant.prompt import PLATFORM_ROUTES, plain_markdown

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_EXACT_ROUTES = {route for _, route in PLATFORM_ROUTES if "{" not in route}

_LABELS = {
    "home": "/platform",
    "platform": "/platform",
    "schools": "/platform/schools",
    "school": "/platform/schools",
    "admins": "/platform/admins",
    "admin": "/platform/admins",
    "team": "/platform/team",
    "employees": "/platform/staff",
    "employee": "/platform/staff",
    "staff": "/platform/staff",
    "plans": "/platform/plans",
    "plan": "/platform/plans",
    "features": "/platform/features",
    "feature": "/platform/features",
    "ai": "/platform/ai",
    "logs": "/platform/logs",
    "log": "/platform/logs",
    "settings": "/platform/settings",
    "profile": "/platform/settings",
    "password": "/platform/settings",
    "password & security": "/platform/settings",
    "notifications": "/platform/settings",
}

_READ_ONLY = frozenset({
    "list_platform_pages",
    "open_platform_page",
    "list_app_pages",
    "navigate_to_page",
    "observe_page",
    "read_current_page",
    "scroll_page",
    "read_data",
})

_READ_BLOCK = re.compile(r"password|token|secret|credential|invite|session", re.IGNORECASE)

CONFIRMATION_TEXT = (
    "That would change platform data. Confirm it on the page before it runs. "
    "I will not change anything from here."
)

_ROUTE_LIST = "\n".join(f"- {label}: {route}" for label, route in PLATFORM_ROUTES)

PLATFORM_READ_TOOLS: list[dict] = [
    {
        "name": "list_platform_pages",
        "description": (
            "Read-only. List the only platform console pages and their routes: "
            + ", ".join(route for _, route in PLATFORM_ROUTES)
            + ". Does not change data."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_platform_page",
        "description": (
            "Read-only. Open one platform console route. page must be one of: "
            + ", ".join(route for _, route in PLATFORM_ROUTES)
            + ". School detail uses /platform/schools/{id} with a real school id. Does not change data."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "page": {"type": "STRING", "description": "Platform route or page name, such as /platform/schools."},
            },
            "required": ["page"],
        },
    },
]


def with_platform_tools(declarations: list[dict]) -> list[dict]:
    """Prepend the platform read tools. Existing declarations stay after them."""
    seen = {str(item.get("name") or "") for item in declarations}
    extra = [tool for tool in PLATFORM_READ_TOOLS if tool["name"] not in seen]
    return [*extra, *declarations]


def canonical_platform_route(raw: str) -> str | None:
    """Return a real console route, or None when the target is not one of them."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        return None
    path = text.split("?", 1)[0].strip()
    lower_path = path.lower().rstrip("/") or "/"
    if lower_path in _EXACT_ROUTES:
        return lower_path
    if lower_path.startswith("/platform/schools/"):
        segment = lower_path.rsplit("/", 1)[-1]
        if _UUID.fullmatch(segment):
            return f"/platform/schools/{segment}"
        return None
    return _LABELS.get(text.lower())


def _name(call: dict) -> str:
    return str((call.get("function") or {}).get("name") or "")


def _args(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _rewrite(call: dict, name: str, args: dict) -> dict:
    function = dict(call.get("function") or {})
    function["name"] = name
    function["arguments"] = json.dumps(args)
    return {**call, "type": "function", "function": function}


def _changes_data(call: dict) -> bool:
    return _name(call) not in _READ_ONLY


def _safe_platform_read(path: str) -> bool:
    bare = path.strip().split("?", 1)[0]
    if not bare.startswith("/api/v1/platform/"):
        return False
    if ".." in bare or "//" in bare:
        return False
    return _READ_BLOCK.search(bare) is None


def apply_platform_tool_policy(result: dict) -> dict:
    """Keep read-only route tools. Replace any data-changing call with a confirmation."""
    message = dict(result.get("message") or {"role": "assistant", "content": ""})
    calls = list(message.get("tool_calls") or [])
    if not calls:
        message["content"] = plain_markdown(str(message.get("content") or ""))
        return {**result, "message": message}
    if any(_changes_data(call) for call in calls):
        message.pop("tool_calls", None)
        message["content"] = CONFIRMATION_TEXT
        message["confirmation_required"] = True
        return {**result, "message": message, "confirmation_required": True, "executed": False}

    kept: list[dict] = []
    notes: list[str] = []
    for call in calls:
        name = _name(call)
        args = _args(call)
        if name == "list_platform_pages":
            notes.append("Platform pages:\n" + _ROUTE_LIST)
            continue
        if name in {"open_platform_page", "navigate_to_page"}:
            route = canonical_platform_route(str(args.get("page") or args.get("path") or ""))
            if route is None:
                notes.append("That page is not in the platform console.")
                continue
            notes.append(f"Open {route}.")
            kept.append(_rewrite(call, "navigate_to_page", {"page": route}))
            continue
        if name == "read_data" and not _safe_platform_read(str(args.get("path") or "")):
            notes.append("That data path is not a platform read.")
            continue
        kept.append(call)

    content = plain_markdown(str(message.get("content") or ""))
    if notes:
        extra = plain_markdown("\n".join(notes))
        content = f"{content}\n{extra}".strip() if content else extra
    message["content"] = content
    if kept:
        message["tool_calls"] = kept
    else:
        message.pop("tool_calls", None)
    return {**result, "message": message, "confirmation_required": False, "executed": True}
