"""Three chalk stages for one doubt: words, a drawn picture, then 3D pointers.

Every stage is a timed list of strokes. The website plays them with the voice
and saves a picture of the board before it is wiped.
"""

from __future__ import annotations

from src.modules.assets.catalog import MODEL_UNAVAILABLE, lookup
from src.modules.classroom.chalk import asset_urls, handwriting, time_events

_STAGE_MS = 4200


def scene_for(topic: str) -> dict:
    found = lookup(topic or "")
    if found.get("model3d_status") != "ready" or not found.get("model3d"):
        return {"status": "unavailable", "model": None, "message": MODEL_UNAVAILABLE, "hotspots": []}
    terms = list(found.get("key_terms") or [])[:4] or [found.get("title") or topic]
    hotspots = []
    for index, term in enumerate(terms):
        label = str(term)[:40]
        hotspots.append(
            {
                "id": f"part-{index}",
                "label": label,
                "say": f"This is the {label.lower()}.",
                "x": round(0.25 + (index % 2) * 0.4, 2),
                "y": round(0.3 + (index // 2) * 0.3, 2),
            }
        )
    model = found["model3d"]
    return {
        "status": "ready",
        "model": {"name": model.get("name"), "url": model.get("url")},
        "message": None,
        "hotspots": hotspots,
    }


def _short(text: str, words: int = 8) -> str:
    return " ".join((text or "").replace(".", " ").split()[:words])


def _diagram_parts(topic: str, quote: str) -> list[str]:
    blob = f"{topic} {quote}".lower()
    parts = []
    if any(word in blob for word in ("sun", "light", "day", "night")):
        parts.append("sun")
    if any(word in blob for word in ("leaf", "plant", "food", "photo")):
        parts.append("leaf")
    if any(word in blob for word in ("water", "rain", "drop")):
        parts.append("drop")
    if "arrow" not in parts:
        parts.append("arrow")
    return parts[:3]


def chalk_lesson(topic: str, speech: str, quote: str) -> dict:
    """Fixed order: handwritten text, hand-drawn diagram, then a 3D pointer scene."""
    heading = (topic or "Today's class")[:80]
    line = _short(quote or speech)
    text_events = handwriting(heading, x=0.08, y=0.12, chalk="yellow", width=0.05)
    text_events += handwriting(line, x=0.08, y=0.32, chalk="white")
    text_stage = _stage("text", 0, speech, text_events, heading)

    picture_events: list[dict] = []
    slots = [(0.16, 0.34), (0.42, 0.34), (0.68, 0.34)]
    for (part, slot) in zip(_diagram_parts(heading, quote), slots, strict=False):
        picture_events.append(
            {"type": "diagram", "part": part, "asset": f"part-{part}", "x": slot[0], "y": slot[1], "scale": 0.18}
        )
    picture_events += handwriting(_short(heading, 4), x=0.12, y=0.62, chalk="yellow", width=0.05)
    picture_stage = _stage(
        "picture",
        1,
        "Here is the same idea as a drawing.",
        picture_events,
        heading,
    )

    scene = scene_for(heading)
    scene_events: list[dict] = [
        {"type": "scene", "status": scene["status"], "model": scene["model"], "message": scene["message"]}
    ]
    if scene["hotspots"]:
        for spot in scene["hotspots"]:
            scene_events.append(
                {
                    "type": "pointer",
                    "hotspot_id": spot["id"],
                    "x": spot["x"],
                    "y": spot["y"],
                    "say": spot["say"],
                    "asset": "cursor-chalk",
                }
            )
        scene_speech = " ".join(spot["say"] for spot in scene["hotspots"])
    else:
        scene_events += handwriting("3d not ready", x=0.12, y=0.4, chalk="white")
        scene_speech = scene["message"] or MODEL_UNAVAILABLE
    scene_stage = _stage("scene3d", 2, scene_speech, scene_events, heading)

    return {
        "style": "chalk_handwriting",
        "typed_text": False,
        "wipe_after_stage": True,
        "assets": asset_urls(),
        "heading": heading,
        "stages": [text_stage, picture_stage, scene_stage],
        "scene3d": scene,
    }


def _stage(name: str, index: int, speech: str, events: list[dict], heading: str) -> dict:
    timed = time_events(events, _STAGE_MS)
    return {
        "stage": name,
        "step_index": index,
        "speech": speech[:400],
        "duration_ms": _STAGE_MS,
        "events": timed,
        "snapshot": {"stage": name, "heading": heading, "style": "chalk_handwriting", "events": timed},
    }
