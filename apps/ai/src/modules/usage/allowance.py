"""Ask the school backend whether this person may spend more tokens, and which model to use.

A backend miss does not stop the reply. A reached cap does.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

logger = logging.getLogger("sybeez.ai.allowance")

_TTL = 20.0
_cache: dict[str, tuple[float, "TokenAllowance"]] = {}
allowance_var: ContextVar[TokenAllowance | None] = ContextVar("ai_token_allowance", default=None)

FALLBACK = "The monthly AI token limit has been reached. A platform admin can raise it."


@dataclass(frozen=True)
class TokenAllowance:
    allowed: bool
    message: str | None
    model: str | None


def reset_allowance_cache() -> None:
    _cache.clear()


def stopped_reply() -> str | None:
    decision = allowance_var.get()
    if decision is None or decision.allowed:
        return None
    return decision.message or FALLBACK


def assigned_model() -> str | None:
    decision = allowance_var.get()
    if decision is None or not decision.allowed:
        return None
    name = (decision.model or "").strip()
    return name or None


def pin_model(provider: object) -> str | None:
    """Return the stop message, or pin the assigned model onto this provider."""
    stopped = stopped_reply()
    if stopped:
        return stopped
    model = assigned_model()
    # Chat stays on qwen3.8-flash from the service config. A stale settings row
    # that names Gemini must not move text calls onto the voice model.
    if not model or "qwen" not in model.lower():
        return None
    provider.model = model
    candidates = getattr(provider, "candidates", None)
    if candidates:
        provider.candidates = [(item[0], item[1], item[2], model) for item in candidates]
    return None


async def load_allowance(auth, bearer: str | None) -> TokenAllowance:
    try:
        school_id = getattr(auth, "school_id", None)
        if school_id is None:
            return TokenAllowance(True, None, None)
        key = f"{getattr(auth, 'user_id', '')}:{school_id}"
        cached = _cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < _TTL:
            return cached[1]
        decision = await _fetch(bearer)
        _cache[key] = (now, decision)
        return decision
    except Exception as exc:
        logger.warning("ai allowance check failed: %s", type(exc).__name__)
        return TokenAllowance(True, None, None)


async def _fetch(bearer: str | None) -> TokenAllowance:
    from src.core.config import get_settings

    settings = get_settings()
    url = f"{settings.core_api_url.rstrip('/')}/api/v1/ai/allowance"
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("ai allowance check failed: %s", type(exc).__name__)
        return TokenAllowance(True, None, None)
    if response.status_code >= 400:
        logger.warning("ai allowance check rejected status=%s", response.status_code)
        return TokenAllowance(True, None, None)
    try:
        payload = response.json()
    except ValueError:
        return TokenAllowance(True, None, None)
    if not isinstance(payload, dict):
        return TokenAllowance(True, None, None)
    model = payload.get("model")
    return TokenAllowance(
        allowed=payload.get("allowed") is not False,
        message=payload.get("message") if isinstance(payload.get("message"), str) else None,
        model=model.strip() if isinstance(model, str) and model.strip() else None,
    )
