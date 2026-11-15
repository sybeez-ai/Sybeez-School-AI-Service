"""Token counts from a provider response, or a length estimate when the provider omits them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    estimated: bool
    model: str
    provider: str


def estimate_usage(prompt: str, reply: str, *, model: str, provider: str) -> TokenUsage:
    """A real count of this call when the provider did not return token usage."""
    return TokenUsage(
        input_tokens=max(1, len(prompt) // 4),
        output_tokens=max(1, len(reply) // 4),
        estimated=True,
        model=model or "unknown",
        provider=provider or "unknown",
    )


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(data: dict, *keys: str) -> int | None:
    for key in keys:
        if key in data:
            parsed = _as_int(data.get(key))
            if parsed is not None:
                return parsed
    return None


def _extract_counts(payload: dict | None) -> tuple[int | None, int | None]:
    """OpenAI prompt/completion tokens, or Gemini prompt/candidate token counts."""
    if not isinstance(payload, dict):
        return None, None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        incoming = _first(usage, "prompt_tokens", "input_tokens", "promptTokenCount")
        outgoing = _first(usage, "completion_tokens", "output_tokens", "candidatesTokenCount", "candidate_tokens")
        if incoming is not None or outgoing is not None:
            return incoming, outgoing
    meta = payload.get("usageMetadata")
    if isinstance(meta, dict):
        return (
            _first(meta, "promptTokenCount", "prompt_tokens", "input_tokens"),
            _first(meta, "candidatesTokenCount", "completion_tokens", "output_tokens"),
        )
    return None, None


def usage_from_provider(
    payload: dict | None, *, prompt: str, reply: str, model: str, provider: str
) -> TokenUsage:
    incoming, outgoing = _extract_counts(payload)
    if incoming is None and outgoing is None:
        return estimate_usage(prompt, reply, model=model, provider=provider)
    estimated = False
    if incoming is None:
        incoming = max(1, len(prompt) // 4)
        estimated = True
    if outgoing is None:
        outgoing = max(1, len(reply) // 4)
        estimated = True
    if incoming <= 0 and outgoing <= 0:
        return estimate_usage(prompt, reply, model=model, provider=provider)
    return TokenUsage(
        input_tokens=max(0, incoming),
        output_tokens=max(0, outgoing),
        estimated=estimated,
        model=model or "unknown",
        provider=provider or "unknown",
    )


def note_usage(provider: object, usage: TokenUsage) -> TokenUsage:
    items = getattr(provider, "usages", None)
    if items is None:
        items = []
        provider.usages = items
    items.append(usage)
    return usage


def usage_start(provider: object) -> int:
    if provider is None:
        return 0
    return len(getattr(provider, "usages", None) or [])


def combine_usages(items: list[TokenUsage]) -> TokenUsage | None:
    if not items:
        return None
    return TokenUsage(
        input_tokens=sum(item.input_tokens for item in items),
        output_tokens=sum(item.output_tokens for item in items),
        estimated=any(item.estimated for item in items),
        model=items[-1].model,
        provider=items[-1].provider,
    )


def usage_record(usage: TokenUsage, *, school_id, user_id, role: str, capability: str = "CHAT") -> dict:
    """Shape stored on ai_messages.meta.usage and sent to the school backend."""
    return {
        "input_tokens": int(usage.input_tokens),
        "output_tokens": int(usage.output_tokens),
        "estimated": bool(usage.estimated),
        "model": usage.model or "unknown",
        "provider": usage.provider or "unknown",
        "capability": capability or "CHAT",
        "role": role,
        "school_id": str(school_id) if school_id else None,
        "user_id": str(user_id) if user_id else None,
        "reported": False,
    }


def collect_usage(provider: object, *, auth, capability: str = "CHAT", start: int = 0) -> dict | None:
    if provider is None or auth is None:
        return None
    items = list(getattr(provider, "usages", None) or [])
    if start < 0:
        start = 0
    usage = combine_usages(items[start:])
    if usage is None:
        return None
    return usage_record(
        usage,
        school_id=getattr(auth, "school_id", None),
        user_id=getattr(auth, "user_id", None),
        role=getattr(auth, "role", None) or "",
        capability=capability,
    )


def post_body(record: dict | None) -> dict | None:
    """Backend payload. Returns None when the row has no stored usage to send."""
    if not isinstance(record, dict):
        return None
    if "input_tokens" not in record or "output_tokens" not in record:
        return None
    try:
        incoming = int(record["input_tokens"])
        outgoing = int(record["output_tokens"])
    except (TypeError, ValueError):
        return None
    if incoming < 0 or outgoing < 0 or (incoming == 0 and outgoing == 0):
        return None
    role = record.get("role")
    if not isinstance(role, str) or not role.strip():
        return None
    return {
        "school_id": record.get("school_id"),
        "user_id": record.get("user_id"),
        "role": role,
        "model": record.get("model") or "unknown",
        "provider": record.get("provider") or "unknown",
        "capability": record.get("capability") or "CHAT",
        "input_tokens": incoming,
        "output_tokens": outgoing,
    }


def stored_usage(meta: dict | None) -> dict | None:
    """Usage object already written on a message. Missing usage is skipped, never invented."""
    if not isinstance(meta, dict):
        return None
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        return None
    if post_body(usage) is None:
        return None
    return usage
