"""Place board actions on the narration clock and interleave chat text."""

import asyncio
import re
from collections.abc import Awaitable, Callable

from src.modules.teacher.protocol import PROTOCOL_VERSION, BoardAction, Narration, dump_action

MS_PER_WORD = 380
MAX_GAP_MS = 8000
MAX_TOTAL_PACING_MS = 90000


def speech_ms(text: str) -> int:
    words = max(1, len(text.split()))
    return words * MS_PER_WORD


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def time_script(chat: str, actions: list[BoardAction]) -> list[BoardAction]:
    """Narration starts at 0. Visual actions are spread across the spoken explanation."""
    spoken = chat.strip() or "Let's look at this together."
    duration = speech_ms(spoken)
    visuals = [action for action in actions if not isinstance(action, Narration)]
    narration = next((action for action in actions if isinstance(action, Narration)), None)
    if narration is None:
        narration = Narration(text=spoken, at_ms=0, duration_ms=duration, page_id=visuals[0].page_id if visuals else "current")
    else:
        narration = narration.model_copy(update={"text": narration.text or spoken, "at_ms": 0, "duration_ms": duration})
    timed: list[BoardAction] = []
    if visuals:
        step = duration / (len(visuals) + 1)
        for index, action in enumerate(visuals, start=1):
            timed.append(action.model_copy(update={"at_ms": int(step * index)}))
    timed.append(narration)
    timed.sort(key=lambda action: (action.at_ms, action.type != "narration"))
    return timed


def rescale_timing(actions: list[dict], duration_ms: int, provider: str) -> list[dict]:
    if duration_ms <= 0:
        return actions
    current = 0
    for action in actions:
        current = max(current, int(action.get("at_ms") or 0))
        if action.get("type") == "narration":
            current = max(current, int(action.get("duration_ms") or 0))
    current = max(current, 1)
    scale = duration_ms / current
    for action in actions:
        action["at_ms"] = int(int(action.get("at_ms") or 0) * scale)
        if action.get("type") == "narration":
            action["duration_ms"] = duration_ms
            action["voice_provider"] = provider
    return actions


def _with_delays(events: list[dict]) -> list[dict]:
    last = 0
    timed: list[dict] = []
    for event in events:
        at_ms = int(event.get("at_ms") or 0)
        item = dict(event)
        item["delay_ms"] = max(0, at_ms - last)
        last = max(last, at_ms)
        timed.append(item)
    return timed


def build_events(
    *,
    session_id: str,
    phase: str,
    step_index: int,
    chat: str,
    actions: list[dict],
    check_prompt: str,
    check_kind: str,
    choices: list[str],
    message_id: str,
    voice: dict | None,
    refused: bool,
    redirected: bool,
) -> list[dict]:
    """Chat sentences and board actions share one clock. Narration is not also a board event."""
    cursor = 0
    body: list[dict] = []
    for sentence in split_sentences(chat):
        body.append({"type": "chat", "content": sentence, "at_ms": cursor})
        cursor += speech_ms(sentence)
    duration = cursor
    voice_used = False
    for action in actions:
        at_ms = int(action.get("at_ms") or 0)
        duration = max(duration, at_ms, int(action.get("duration_ms") or 0) if action.get("type") == "narration" else 0)
        if action.get("type") == "narration":
            clip = voice if voice and not voice_used else None
            voice_used = True
            body.append(
                {
                    "type": "narration",
                    "at_ms": at_ms,
                    "text": action.get("text") or "",
                    "duration_ms": int(action.get("duration_ms") or 0),
                    "page_id": action.get("page_id"),
                    "action_id": action.get("id"),
                    "voice": clip,
                }
            )
        else:
            body.append({"type": "board", "at_ms": at_ms, "action": action})
    body.sort(key=lambda item: (item["at_ms"], 0 if item["type"] in {"chat", "narration"} else 1))
    if check_prompt:
        body.append(
            {
                "type": "check",
                "at_ms": duration,
                "prompt": check_prompt,
                "kind": check_kind or "ask",
                "choices": choices,
            }
        )
    events = [
        {
            "type": "meta",
            "at_ms": 0,
            "session_id": session_id,
            "phase": phase,
            "step_index": step_index,
            "protocol": PROTOCOL_VERSION,
            "refused": refused,
            "redirected": redirected,
        },
        *body,
        {"type": "done", "at_ms": duration, "session_id": session_id, "message_id": message_id, "phase": phase},
    ]
    return _with_delays(events)


async def pace_events(
    events: list[dict],
    *,
    pace: bool,
    sleep: Callable[[float], Awaitable[None]] | None = None,
):
    """Optional server-side pacing. Gaps are capped so one lesson cannot hold the worker open."""
    sleeper = sleep or asyncio.sleep
    spent = 0
    for event in events:
        delay = int(event.get("delay_ms") or 0)
        if pace and delay > 0 and spent < MAX_TOTAL_PACING_MS:
            wait = min(delay, MAX_GAP_MS, MAX_TOTAL_PACING_MS - spent)
            await sleeper(wait / 1000)
            spent += wait
        yield event


def dumps_actions(actions: list[BoardAction]) -> list[dict]:
    return [dump_action(action) for action in actions]
