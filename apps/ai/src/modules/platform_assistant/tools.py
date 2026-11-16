"""Platform tools for the typed agent step.

Reads point at the real console routes. A tool that would change data is not
run here. The call is returned so the console can show a confirmation card.
"""

from __future__ import annotations

import json
import re

from src.modules.platform_assistant.prompt import (
    PLATFORM_ROUTES,
    console_path,
    format_platform_routes,
    plain_markdown,
)

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ID_PLACEHOLDER = re.compile(r"\{id\}|(?<![\w]):id\b", re.IGNORECASE)


def _exact_routes() -> frozenset[str]:
    found: set[str] = set()
    for _, route in PLATFORM_ROUTES:
        if "{" in route or ":id" in route:
            continue
        path = console_path(route)
        if path:
            found.add(path)
    return frozenset(found)


_EXACT_ROUTES = _exact_routes()
_EXACT_ROUTE_CSV = ", ".join(
    route for _, route in PLATFORM_ROUTES if "{" not in route and ":id" not in route
)

_LABELS = {
    "home": "/platform",
    "platform": "/platform",
    "schools": "/platform/schools",
    "school": "/platform/schools",
    "admins": "/platform/admins",
    "admin": "/platform/admins",
    "team": "/platform/staff",
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
    "profile": "/platform/profile",
    "attention": "/platform/attention",
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
    "platform_report",
})

# Names the console knows how to run. Anything else is dropped.
_CLIENT_ACTIONS = _READ_ONLY | frozenset({
    "create_school",
    "update_school",
    "suspend_school",
    "archive_school",
    "delete_school",
    "add_school_admin",
    "invite_school_admin",
    "remove_school_admin",
    "create_plan",
    "update_plan",
    "delete_plan",
    "set_school_feature",
    "set_school_token_limit",
    "set_group_token_limit",
    "set_person_token_limit",
    "invite_team_member",
    "update_team_role",
    "revoke_team_member",
    "invite_employee",
    "update_employee_role",
    "revoke_employee",
    "update_profile",
    "change_password",
    "set_notification_preference",
    "set_school_trial",
    "reactivate_school",
    "update_school_commercial",
    "reset_school_admin_password",
    "clear_school_admin_mfa",
    "delete_school_subscription",
    "delete_audit_entry",
    "restore_employee",
    "delete_employee",
    "resend_employee_invite",
    "cancel_employee_invite",
    "update_ai_settings",
    "mark_notifications_read",
    "delete_platform_record",
    "set_platform_fee",
    "click_element",
    "type_in_element",
    "select_option",
})

_WRITES = frozenset({
    "create_school",
    "update_school",
    "suspend_school",
    "archive_school",
    "delete_school",
    "add_school_admin",
    "invite_school_admin",
    "remove_school_admin",
    "create_plan",
    "update_plan",
    "delete_plan",
    "set_school_feature",
    "set_school_token_limit",
    "set_group_token_limit",
    "set_person_token_limit",
    "invite_team_member",
    "update_team_role",
    "revoke_team_member",
    "invite_employee",
    "update_employee_role",
    "revoke_employee",
    "update_profile",
    "change_password",
    "set_notification_preference",
    "set_school_trial",
    "reactivate_school",
    "update_school_commercial",
    "reset_school_admin_password",
    "clear_school_admin_mfa",
    "delete_school_subscription",
    "delete_audit_entry",
    "restore_employee",
    "delete_employee",
    "resend_employee_invite",
    "cancel_employee_invite",
    "update_ai_settings",
    "mark_notifications_read",
    "delete_platform_record",
    "set_platform_fee",
    "type_in_element",
    "select_option",
})

_MUTATING_CLICK = re.compile(
    r"\b(create|add|new|update|edit|save|delete|remove|submit|send|pay|approve|revoke|disable|invite|assign|change|archive|suspend)\b",
    re.IGNORECASE,
)

_READ_BLOCK = re.compile(r"password|token|secret|credential|invite|session", re.IGNORECASE)

_ROUTE_LIST = format_platform_routes()

PLATFORM_READ_TOOLS: list[dict] = [
    {
        "name": "list_platform_pages",
        "description": (
            "Read-only. List the only platform console pages and their routes: "
            + _EXACT_ROUTE_CSV
            + ". A school detail URL is /platform/schools/ plus a real school id, and only when that id is known. "
            "If no school id is known, the page is /platform/schools. Does not change data."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_platform_page",
        "description": (
            "Read-only. Open one platform console route. page must be one of: "
            + _EXACT_ROUTE_CSV
            + ". Pass a school detail path only when the school id is known. "
            "Do not pass a placeholder id. Does not change data."
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


def mentions_id_placeholder(raw: str) -> bool:
    """True when a path still contains a raw {id} or :id placeholder."""
    return _ID_PLACEHOLDER.search(raw or "") is not None


def canonical_platform_route(raw: str) -> str | None:
    """Return a real console route, or None when the target is not one of them.

    Comparison ignores a trailing slash, so `/platform/profile/` is `/platform/profile`.
    A school detail path is returned only when the id is a real school id.
    """
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text or mentions_id_placeholder(text):
        return None
    path = console_path(text)
    if path == "/platform/team" or path.startswith("/platform/team/"):
        return "/platform/staff"
    if path in _EXACT_ROUTES:
        return path
    if path.startswith("/platform/schools/"):
        segment = path.rsplit("/", 1)[-1]
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


_DESTRUCTIVE = frozenset({
    "delete_school",
    "remove_school_admin",
    "delete_plan",
    "revoke_team_member",
    "revoke_employee",
    "suspend_school",
    "archive_school",
    "delete_school_subscription",
    "delete_audit_entry",
    "delete_employee",
    "cancel_employee_invite",
    "delete_platform_record",
})
_DESTRUCTIVE_CLICK = re.compile(r"\b(delete|remove|revoke|suspend|archive)\b", re.I)


def _needs_confirm(call: dict) -> bool:
    """Only destructive actions wait for the card. Creates and edits run immediately."""
    name = _name(call)
    if name in _DESTRUCTIVE:
        return True
    if name != "click_element":
        return False
    args = _args(call)
    label = f"{args.get('label') or ''} {args.get('ref') or ''}"
    return _DESTRUCTIVE_CLICK.search(label) is not None


def _safe_platform_read(path: str) -> bool:
    bare = path.strip().split("?", 1)[0]
    if not bare.startswith("/api/v1/platform/"):
        return False
    if ".." in bare or "//" in bare:
        return False
    return _READ_BLOCK.search(bare) is None


def apply_platform_tool_policy(result: dict) -> dict:
    """Return tool calls for the console. Writes stay unexecuted until the card is confirmed."""
    message = dict(result.get("message") or {"role": "assistant", "content": ""})
    calls = list(message.get("tool_calls") or [])
    if not calls:
        message["content"] = plain_markdown(str(message.get("content") or ""))
        return {**result, "message": message, "confirmation_required": False, "executed": True}

    kept: list[dict] = []
    notes: list[str] = []
    for call in calls:
        name = _name(call)
        if name not in _CLIENT_ACTIONS:
            notes.append("That action is not available.")
            continue
        args = _args(call)
        if name == "list_platform_pages":
            notes.append("Platform pages:\n" + _ROUTE_LIST)
            continue
        if name in {"open_platform_page", "navigate_to_page"}:
            requested = str(args.get("page") or args.get("path") or "")
            route = canonical_platform_route(requested)
            if route is None:
                if mentions_id_placeholder(requested):
                    notes.append("Open the school from Schools (/platform/schools).")
                else:
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
    needs_confirm = any(_needs_confirm(call) for call in kept)
    if needs_confirm and "confirm" not in content.lower():
        message["content"] = (content + "\nConfirm this on the card. Nothing changes until you do.").strip()
    return {
        **result,
        "message": message,
        "confirmation_required": needs_confirm,
        "executed": not needs_confirm,
    }
