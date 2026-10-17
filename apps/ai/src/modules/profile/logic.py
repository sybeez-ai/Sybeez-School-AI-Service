"""Pure learning-profile logic: update from outcomes, readable report, and the teaching prompt block."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

STYLES = ("visual", "worked_examples", "stories", "step_by_step")
STYLE_LABELS = {
    "visual": "pictures, diagrams and 3D views",
    "worked_examples": "worked examples",
    "stories": "stories and everyday analogies",
    "step_by_step": "small step-by-step explanations",
}
ALPHA = 0.25
MIN_ATTEMPTS_FOR_BEST = 3
MAX_TOPICS = 60
RETENTION = (
    "Kept only while the student is enrolled. It records which teaching styles worked and which topics were "
    "hard, never conversation text. The student can correct or reset it at any time, and parents can ask their child to."
)


def empty_profile() -> dict[str, Any]:
    return {
        "styles": {s: {"score": 0.5, "attempts": 0} for s in STYLES},
        "topics": {},
        "speaking": {"sessions": 0, "minutes": 0.0, "last": None},
        "reading": {"sessions": 0, "pages": 0, "last": None},
        "style_override": None,
        "dismissed_topics": [],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_topic(topic: str) -> str:
    return " ".join((topic or "").split())[:80].lower()


def apply_event(profile: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    """Return a new profile with one event folded in. Unknown or malformed events are ignored."""
    p = deepcopy(profile) if profile else empty_profile()
    base = empty_profile()
    for key, value in base.items():
        p.setdefault(key, value)
    kind = event.get("kind")
    if kind == "outcome":
        topic = _clean_topic(str(event.get("topic", "")))
        correct = bool(event.get("correct"))
        style = event.get("style")
        if style in STYLES:
            s = p["styles"].setdefault(style, {"score": 0.5, "attempts": 0})
            s["score"] = round(s["score"] + ALPHA * ((1.0 if correct else 0.0) - s["score"]), 4)
            s["attempts"] = int(s["attempts"]) + 1
        if topic:
            t = p["topics"].setdefault(topic, {"tries": 0, "misses": 0, "last": None})
            t["tries"] += 1
            t["misses"] += 0 if correct else 1
            t["last"] = _now()
            if correct and topic in p["dismissed_topics"]:
                p["dismissed_topics"].remove(topic)
            if len(p["topics"]) > MAX_TOPICS:
                oldest = sorted(p["topics"].items(), key=lambda kv: kv[1].get("last") or "")[0][0]
                p["topics"].pop(oldest, None)
    elif kind == "speaking":
        minutes = max(0.0, min(float(event.get("minutes", 0) or 0), 120.0))
        p["speaking"]["sessions"] += 1
        p["speaking"]["minutes"] = round(p["speaking"]["minutes"] + minutes, 2)
        p["speaking"]["last"] = _now()
    elif kind == "reading":
        pages = max(0, min(int(event.get("pages", 0) or 0), 200))
        p["reading"]["sessions"] += 1
        p["reading"]["pages"] += pages
        p["reading"]["last"] = _now()
    return p


def best_style(p: dict[str, Any]) -> str | None:
    if p.get("style_override") in STYLES:
        return p["style_override"]
    ranked = [
        (v["score"], k) for k, v in p["styles"].items() if v["attempts"] >= MIN_ATTEMPTS_FOR_BEST
    ]
    if not ranked:
        return None
    score, style = max(ranked)
    return style if score >= 0.55 else None


def weak_topics(p: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for topic, t in p["topics"].items():
        if topic in p.get("dismissed_topics", []):
            continue
        if t["misses"] >= 2 and t["misses"] / max(t["tries"], 1) >= 0.5:
            out.append({"topic": topic, "misses": t["misses"], "tries": t["tries"]})
    return sorted(out, key=lambda x: (-x["misses"], x["topic"]))[:8]


def strong_topics(p: dict[str, Any]) -> list[str]:
    return sorted(
        t for t, v in p["topics"].items() if v["tries"] >= 3 and v["misses"] / v["tries"] <= 0.2
    )[:8]


def report(p: dict[str, Any] | None) -> dict[str, Any]:
    p = apply_event(p, {})  # fills defaults
    best = best_style(p)
    lines = []
    if best:
        lines.append(f"Learns best with {STYLE_LABELS[best]}.")
    else:
        lines.append("Still learning how this student learns best; more lessons will help.")
    weak = weak_topics(p)
    if weak:
        lines.append("Needs more practice: " + ", ".join(w["topic"] for w in weak) + ".")
    strong = strong_topics(p)
    if strong:
        lines.append("Doing well in: " + ", ".join(strong) + ".")
    if p["speaking"]["sessions"]:
        lines.append(
            f"Spoke with the AI teacher in {p['speaking']['sessions']} sessions "
            f"({round(p['speaking']['minutes'])} minutes)."
        )
    if p["reading"]["sessions"]:
        lines.append(f"Read {p['reading']['pages']} pages across {p['reading']['sessions']} reading sessions.")
    return {
        "best_style": best,
        "best_style_label": STYLE_LABELS.get(best) if best else None,
        "style_override": p.get("style_override"),
        "styles": {k: {"score": v["score"], "attempts": v["attempts"]} for k, v in p["styles"].items()},
        "weak_topics": weak,
        "strong_topics": strong,
        "speaking": p["speaking"],
        "reading": p["reading"],
        "summary": lines,
        "retention": RETENTION,
    }


def prompt_block(p: dict[str, Any] | None) -> str:
    """Teaching adaptation hints for the AI teacher. Empty until there is real evidence."""
    if not p:
        return ""
    p = apply_event(p, {})
    best = best_style(p)
    weak = weak_topics(p)
    if not best and not weak:
        return ""
    lines = ["Learning profile of this student (from their own past results; adapt, do not mention it):"]
    if best:
        lines.append(f"- Teaches best through {STYLE_LABELS[best]}: lead with that style, then check understanding.")
    if weak:
        lines.append(
            "- Struggles with: " + ", ".join(w["topic"] for w in weak[:5])
            + ". Go slower there, use one more example and a quick check."
        )
    strong = strong_topics(p)
    if strong:
        lines.append("- Strong in: " + ", ".join(strong[:5]) + ". Move faster on these.")
    return "\n".join(lines)


def correct(p: dict[str, Any] | None, *, style_override: str | None, clear_style: bool, dismiss_topics: list[str]) -> dict[str, Any]:
    q = apply_event(p, {})
    if clear_style:
        q["style_override"] = None
    elif style_override in STYLES:
        q["style_override"] = style_override
    for t in dismiss_topics[:20]:
        c = _clean_topic(t)
        if c and c not in q["dismissed_topics"]:
            q["dismissed_topics"].append(c)
    return q
