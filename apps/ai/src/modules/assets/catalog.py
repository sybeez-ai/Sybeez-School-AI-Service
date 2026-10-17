"""Teaching asset catalog: topic -> curated images / GLB model, served from S3 via CloudFront.

The manifest (manifest.json) is produced by scripts/ingest_teaching_assets.py. Nothing here
calls Wikipedia or any third-party host at runtime.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_MANIFEST = Path(__file__).with_name("manifest.json")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "of", "a", "an", "and", "in", "to", "is", "what", "why", "how", "do", "we", "have", "are", "about", "explain", "me"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    try:
        return json.loads(_MANIFEST.read_text())
    except FileNotFoundError:
        return {"version": 1, "cdn": "", "topics": {}, "models": {}}


def _score(topic: dict, q_tokens: set[str], q_text: str) -> float:
    names = [topic["title"], topic["slug"].replace("-", " "), *topic.get("aliases", [])]
    best = 0.0
    for name in names:
        n_tokens = _tokens(name)
        if not n_tokens:
            continue
        if q_text and (q_text in name.lower() or name.lower() in q_text):
            best = max(best, 1.0)
        overlap = len(q_tokens & n_tokens) / len(n_tokens)
        best = max(best, overlap)
    terms = _tokens(" ".join(topic.get("key_terms", [])))
    if terms and q_tokens:
        best = max(best, 0.4 * len(q_tokens & terms) / max(1, len(q_tokens)))
    return best


def clean_regions(raw) -> list[dict]:
    """Per-image pointing regions from the manifest: [{label, x, y}] with x,y clamped to 0..1."""
    out: list[dict] = []
    for r in (raw or [])[:12]:
        try:
            label = str(r["label"]).strip()[:40]
            x, y = float(r["x"]), float(r["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if label:
            out.append({"label": label, "x": round(min(1.0, max(0.0, x)), 3), "y": round(min(1.0, max(0.0, y)), 3)})
    return out


def library(*, subject: str = "", class_no: int | None = None) -> list[dict]:
    """Browsable list of every topic with pictures and/or a 3D model."""
    manifest = load_manifest()
    items = []
    for topic in manifest["topics"].values():
        if subject and topic["subject"].lower() != subject.lower():
            continue
        if class_no and class_no not in topic.get("classes", []):
            continue
        items.append({
            "slug": topic["slug"], "title": topic["title"], "subject": topic["subject"],
            "classes": topic.get("classes", []), "images": len(topic.get("images", [])),
            "has_3d": bool(manifest["models"].get(topic.get("model3d") or "")),
            "thumb": (topic.get("images") or [{}])[0].get("url"),
        })
    return sorted(items, key=lambda i: (i["subject"], i["title"]))


def lookup(query: str, *, subject: str = "", class_no: int | None = None, limit: int = 3) -> dict:
    """Best topic match; always returns a safe answer (placeholder when nothing matches)."""
    manifest = load_manifest()
    q_text = (query or "").strip().lower()
    q_tokens = _tokens(q_text)
    ranked: list[tuple[float, dict]] = []
    for topic in manifest["topics"].values():
        s = _score(topic, q_tokens, q_text)
        if subject and topic["subject"].lower() == subject.lower():
            s += 0.05
        if class_no and class_no in topic.get("classes", []):
            s += 0.05
        if s >= 0.5:
            ranked.append((s, topic))
    ranked.sort(key=lambda x: -x[0])
    if not ranked:
        return {"found": False, "source": "placeholder", "query": query[:120], "images": [], "model3d": None, "key_terms": [],
                "note": "No curated asset for this topic yet; draw it on the board and describe it in words."}
    score, topic = ranked[0]
    model = manifest["models"].get(topic.get("model3d") or "")
    return {
        "found": True,
        "source": "s3",
        "score": round(min(score, 1.0), 2),
        "slug": topic["slug"],
        "title": topic["title"],
        "subject": topic["subject"],
        "classes": topic.get("classes", []),
        "key_terms": topic.get("key_terms", []),
        "images": [
            {
                **{k: img[k] for k in ("url", "caption", "alt", "license", "license_url", "author", "source")},
                "regions": clean_regions(img.get("regions")),
            }
            for img in topic["images"][:limit]
        ],
        "model3d": ({"name": topic["model3d"], "url": model["url"], "license": model["license"]} if model else None),
    }
