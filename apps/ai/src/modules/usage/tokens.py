"""Token counts taken from the provider response.

Qwen and Gemini never fall back to a character estimate. When DashScope or
Gemini omits usage, the row is marked estimated with zeros and is not stored.
Other providers still use a length estimate when they send no usage object.
"""

from __future__ import annotations

from dataclasses import dataclass

EXACT_PROVIDERS = {"qwen", "dashscope", "gemini"}


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    estimated: bool
    model: str
    provider: str
    total_tokens: int = 0
    input_audio_tokens: int = 0
    input_text_tokens: int = 0
    output_audio_tokens: int = 0
    output_text_tokens: int = 0


def exact_provider(provider: str | None) -> bool:
    return (provider or "").strip().lower() in EXACT_PROVIDERS


def _blank_exact(item: TokenUsage) -> bool:
    return (
        item.estimated
        and exact_provider(item.provider)
        and item.input_tokens == 0
        and item.output_tokens == 0
        and item.total_tokens == 0
    )


def estimate_usage(prompt: str, reply: str, *, model: str, provider: str) -> TokenUsage:
    """A length estimate. Not used for Qwen or Gemini."""
    incoming = max(1, len(prompt) // 4)
    outgoing = max(1, len(reply) // 4)
    return TokenUsage(
        input_tokens=incoming,
        output_tokens=outgoing,
        estimated=True,
        model=model or "unknown",
        provider=provider or "unknown",
        total_tokens=incoming + outgoing,
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


def _modality(details: object) -> tuple[int, int]:
    """Audio and text token counts from a Gemini modality list."""
    audio = text = 0
    if not isinstance(details, list):
        return 0, 0
    for item in details:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("modality") or "").upper()
        count = _as_int(item.get("tokenCount") if "tokenCount" in item else item.get("token_count")) or 0
        if count < 0:
            continue
        if "AUDIO" in kind:
            audio += count
        elif "TEXT" in kind:
            text += count
    return audio, text


def _output_details(meta: dict) -> object:
    details = meta.get("candidatesTokensDetails")
    if isinstance(details, list):
        return details
    return meta.get("responseTokensDetails")


@dataclass(frozen=True)
class _Counts:
    incoming: int | None
    outgoing: int | None
    total: int | None
    input_audio: int = 0
    input_text: int = 0
    output_audio: int = 0
    output_text: int = 0


def _from_usage_dict(usage: dict) -> _Counts | None:
    incoming = _first(usage, "prompt_tokens", "input_tokens", "promptTokenCount")
    outgoing = _first(usage, "completion_tokens", "output_tokens", "candidatesTokenCount", "responseTokenCount")
    total = _first(usage, "total_tokens", "totalTokenCount")
    if incoming is None and outgoing is None and total is None:
        return None
    in_audio, in_text = _modality(usage.get("promptTokensDetails") or usage.get("prompt_tokens_details"))
    out_details = usage.get("candidatesTokensDetails")
    if not isinstance(out_details, list):
        out_details = usage.get("responseTokensDetails")
    out_audio, out_text = _modality(out_details)
    return _Counts(incoming, outgoing, total, in_audio, in_text, out_audio, out_text)


def _extract_counts(payload: dict | None) -> _Counts | None:
    """OpenAI/DashScope usage, or Gemini usageMetadata. None when the provider sent neither."""
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        found = _from_usage_dict(usage)
        if found is not None:
            return found
    meta = payload.get("usageMetadata")
    if isinstance(meta, dict):
        incoming = _first(meta, "promptTokenCount", "prompt_tokens", "input_tokens")
        outgoing = _first(meta, "candidatesTokenCount", "responseTokenCount", "completion_tokens", "output_tokens")
        total = _first(meta, "totalTokenCount", "total_tokens")
        if incoming is None and outgoing is None and total is None:
            return None
        in_audio, in_text = _modality(meta.get("promptTokensDetails"))
        out_audio, out_text = _modality(_output_details(meta))
        return _Counts(incoming, outgoing, total, in_audio, in_text, out_audio, out_text)
    return None


def _blank(model: str, provider: str) -> TokenUsage:
    return TokenUsage(0, 0, True, model or "unknown", provider or "unknown", total_tokens=0)


def usage_from_provider(
    payload: dict | None, *, prompt: str, reply: str, model: str, provider: str
) -> TokenUsage:
    found = _extract_counts(payload)
    if found is None:
        if exact_provider(provider):
            return _blank(model, provider)
        return estimate_usage(prompt, reply, model=model, provider=provider)
    estimated = False
    incoming = found.incoming
    outgoing = found.outgoing
    if incoming is None:
        if exact_provider(provider):
            incoming = 0
        else:
            incoming = max(1, len(prompt) // 4)
            estimated = True
    if outgoing is None:
        if exact_provider(provider):
            outgoing = 0
        else:
            outgoing = max(1, len(reply) // 4)
            estimated = True
    if not exact_provider(provider) and incoming <= 0 and outgoing <= 0:
        return estimate_usage(prompt, reply, model=model, provider=provider)
    total = found.total if found.total is not None else incoming + outgoing
    return TokenUsage(
        input_tokens=max(0, incoming),
        output_tokens=max(0, outgoing),
        estimated=estimated,
        model=model or "unknown",
        provider=provider or "unknown",
        total_tokens=max(0, total),
        input_audio_tokens=found.input_audio,
        input_text_tokens=found.input_text,
        output_audio_tokens=found.output_audio,
        output_text_tokens=found.output_text,
    )


def usage_from_live_snapshots(snapshots: list | None, *, model: str) -> TokenUsage | None:
    """Sum one usageMetadata per Live turn. The caller keeps the last snapshot of each turn."""
    if not isinstance(snapshots, list):
        return None
    items: list[TokenUsage] = []
    for snap in snapshots[:200]:
        if not isinstance(snap, dict):
            continue
        if isinstance(snap.get("usageMetadata"), dict) or isinstance(snap.get("usage"), dict):
            payload = snap
        else:
            payload = {"usageMetadata": snap}
        usage = usage_from_provider(payload, prompt="", reply="", model=model, provider="gemini")
        if _blank_exact(usage):
            continue
        items.append(usage)
    return combine_usages(items)


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
    real = [item for item in items if not _blank_exact(item)]
    if not real:
        return items[-1]
    return TokenUsage(
        input_tokens=sum(item.input_tokens for item in real),
        output_tokens=sum(item.output_tokens for item in real),
        estimated=any(item.estimated for item in real),
        model=real[-1].model,
        provider=real[-1].provider,
        total_tokens=sum(item.total_tokens for item in real),
        input_audio_tokens=sum(item.input_audio_tokens for item in real),
        input_text_tokens=sum(item.input_text_tokens for item in real),
        output_audio_tokens=sum(item.output_audio_tokens for item in real),
        output_text_tokens=sum(item.output_text_tokens for item in real),
    )


def usage_record(usage: TokenUsage, *, school_id, user_id, role: str, capability: str = "CHAT") -> dict:
    """Shape stored on ai_messages.meta.usage and sent to the school backend."""
    return {
        "input_tokens": int(usage.input_tokens),
        "output_tokens": int(usage.output_tokens),
        "total_tokens": int(usage.total_tokens),
        "input_audio_tokens": int(usage.input_audio_tokens),
        "input_text_tokens": int(usage.input_text_tokens),
        "output_audio_tokens": int(usage.output_audio_tokens),
        "output_text_tokens": int(usage.output_text_tokens),
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
    if usage is None or _blank_exact(usage):
        return None
    return usage_record(
        usage,
        school_id=getattr(auth, "school_id", None),
        user_id=getattr(auth, "user_id", None),
        role=getattr(auth, "role", None) or "",
        capability=capability,
    )


def post_body(record: dict | None) -> dict | None:
    """Backend payload. Qwen and Gemini estimates are dropped. A zero row is dropped."""
    if not isinstance(record, dict):
        return None
    if record.get("estimated") and exact_provider(str(record.get("provider") or "")):
        return None
    if "input_tokens" not in record or "output_tokens" not in record:
        return None
    try:
        incoming = int(record["input_tokens"])
        outgoing = int(record["output_tokens"])
        total = int(record["total_tokens"]) if record.get("total_tokens") not in (None, "") else incoming + outgoing
        input_audio = int(record.get("input_audio_tokens") or 0)
        input_text = int(record.get("input_text_tokens") or 0)
        output_audio = int(record.get("output_audio_tokens") or 0)
        output_text = int(record.get("output_text_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        total = incoming + outgoing
    if incoming < 0 or outgoing < 0 or (incoming == 0 and outgoing == 0 and total == 0):
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
        "total_tokens": total,
        "input_audio_tokens": max(0, input_audio),
        "input_text_tokens": max(0, input_text),
        "output_audio_tokens": max(0, output_audio),
        "output_text_tokens": max(0, output_text),
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
