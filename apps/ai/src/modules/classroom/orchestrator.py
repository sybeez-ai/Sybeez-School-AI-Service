"""One student doubt about today's uploaded page.

Order: safety, retrieval, memory, one explanation, board snapshots, 3D hotspots.
The model is called at most once. A refusal or a clarifying question costs nothing.
"""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from src.core.budget import DAILY_LIMIT_MESSAGE, allow_model
from src.core.exceptions import AppError, ForbiddenError
from src.core.security import AuthContext
from src.modules.assets.catalog import MODEL_UNAVAILABLE
from src.modules.chat.persona import assistant_name
from src.modules.classroom.board import chalk_lesson
from src.modules.classroom.material import ClassroomMaterial
from src.modules.teacher.safety import assess

logger = logging.getLogger("sybeez.ai.classroom")

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "to", "and", "in", "on", "for", "is", "it", "my", "me",
    "do", "does", "how", "what", "why", "please", "today", "class", "teacher",
}
LISTENING = {
    "barge_in": True,
    "end_of_turn_silence_ms": 700,
    "clarify_when_unsure": True,
    "max_listen_seconds": 20,
}


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall((text or "").lower()) if word not in _STOP and len(word) > 2}


def citations_for(page: dict, message: str) -> list[dict]:
    """Quotes from today's upload that share words with the doubt. Never invents a source."""
    question = _words(message) | _words(page.get("topic") or "")
    ranked: list[tuple[int, dict]] = []
    for chunk in page.get("chunks") or []:
        overlap = len(question & _words(chunk.get("text") or ""))
        if overlap:
            ranked.append((overlap, chunk))
    ranked.sort(key=lambda item: -item[0])
    chosen = [chunk for _score, chunk in ranked[:2]]
    if not chosen and page.get("chunks"):
        chosen = [page["chunks"][0]]
    found = []
    for chunk in chosen:
        text = " ".join(str(chunk.get("text") or "").split())
        if not text:
            continue
        found.append({"source": chunk.get("source") or "Today's class", "quote": text[:280]})
    return found


def off_page(page: dict, message: str) -> bool:
    """True when the doubt shares no words with today's topic, teaching, or homework."""
    page_words = _words(page.get("topic") or "") | _words(page.get("taught") or "") | _words(page.get("homework") or "")
    asked = _words(message)
    if not page_words:
        return False
    if not asked:
        return True
    return asked.isdisjoint(page_words)


def _fallback_speech(page: dict, quote: str) -> str:
    topic = page.get("topic") or "today's lesson"
    example = page.get("homework") or "something you can see at home or at school"
    return (
        f"Today your teacher taught {topic}. {quote} "
        f"An everyday way to remember it: {example} "
        f"Can you say one thing from today's page in your own words?"
    )


class ClassroomOrchestrator:
    def __init__(self, material: ClassroomMaterial | None = None, llm=None) -> None:
        self.material = material or ClassroomMaterial()
        self.llm = llm

    async def turn(self, auth: AuthContext, body, bearer: str | None) -> dict:
        if auth.role != "STUDENT":
            raise ForbiddenError("The AI teacher is for students. Other roles use the AI assistant.")
        if auth.school_id is None:
            raise ForbiddenError("School context required")
        decision = assess(body.message, grade_band="middle", awaiting_check=False)
        if not decision.allowed or decision.redirect:
            return _stopped(decision.student_message, grounded=False, clarify=None)
        page = await self.material.today(bearer, body.class_section_id, body.on)
        if not page.get("chunks"):
            return _stopped(
                "Your teacher has not uploaded today's page for your class yet. "
                "Ask them to add what was taught, or tell me which part of today's lesson you mean.",
                grounded=False,
                clarify="Which part of today's class or homework is your doubt about?",
            )
        if off_page(page, body.message):
            topic = page.get("topic") or "today's lesson"
            return _stopped(
                f"Today's class was {topic}. I can only explain that page and its homework. "
                f"Which part of {topic} is confusing?",
                grounded=False,
                clarify=f"Which part of {topic} should we look at?",
                topic=topic,
            )
        if not await allow_model(auth):
            raise AppError(DAILY_LIMIT_MESSAGE, code="rate_limited", status_code=429)
        quotes = citations_for(page, body.message)
        quote = quotes[0]["quote"] if quotes else ""
        speech = await self._explain(page, body.message, quote, list(body.session_memory))
        lesson = chalk_lesson(page.get("topic") or "", speech, quote)
        for stage in lesson["stages"]:
            saved = await self.material.save_picture(
                bearer,
                {
                    "student_user_id": str(auth.user_id),
                    "class_section_id": str(body.class_section_id),
                    "on": body.on,
                    "topic": page.get("topic") or "",
                    "session_id": str(body.session_id) if body.session_id else None,
                    "step_index": stage["step_index"],
                    "caption": stage["stage"],
                    "snapshot": stage["snapshot"],
                },
            )
            stage["picture_id"] = saved or str(uuid4())
        concept = page.get("topic") or "today's lesson"
        note = f"Asked: {body.message[:180]}"
        await self.material.remember(
            bearer,
            {
                "scope": "student",
                "student_user_id": str(auth.user_id),
                "class_section_id": str(body.class_section_id),
                "kind": "doubt",
                "concept": concept,
                "note": note,
                "on": body.on,
            },
        )
        await self.material.remember(
            bearer,
            {
                "scope": "class",
                "class_section_id": str(body.class_section_id),
                "kind": "common_doubt",
                "concept": concept,
                "note": "A student asked about today's page.",
                "on": body.on,
            },
        )
        return {
            "persona": assistant_name("STUDENT"),
            "topic": concept,
            "grounded": bool(quotes),
            "citations": quotes,
            "clarify": None,
            "speech": speech,
            "board": {key: value for key, value in lesson.items() if key != "scene3d"},
            "scene3d": lesson["scene3d"],
            "memory_written": [f"doubt:{concept}"],
            "listening": dict(LISTENING),
        }

    async def _explain(self, page: dict, message: str, quote: str, session_memory: list[str]) -> str:
        fallback = _fallback_speech(page, quote)
        if self.llm is None:
            return fallback
        memory = " ".join(session_memory)[:500]
        prompt = (
            "Explain this school doubt in 5 to 8 short friendly sentences for class 6. "
            "Use only the teacher's text. Quote it. Give one everyday example. End with one check question. "
            "Do not add facts that are not in the text.\n"
            f"Topic: {page.get('topic')}\nTeacher wrote: {quote}\n"
            f"Homework: {page.get('homework') or ''}\nSession notes: {memory}\nStudent: {message}"
        )
        try:
            raw = await self.llm.complete(
                system="You are the AI teacher. Stay on the uploaded page. Never call yourself anything else.",
                user=prompt,
            )
        except Exception as exc:
            logger.info("classroom model unavailable: %s", type(exc).__name__)
            return fallback
        text = " ".join(str(raw or "").split())
        if quote and quote[:40] not in text:
            text = f"{quote} {text}".strip()
        return text[:1200] or fallback


def _stopped(speech: str, *, grounded: bool, clarify: str | None, topic: str = "") -> dict:
    return {
        "persona": assistant_name("STUDENT"),
        "topic": topic,
        "grounded": grounded,
        "citations": [],
        "clarify": clarify,
        "speech": speech,
        "board": {
            "style": "chalk_handwriting",
            "typed_text": False,
            "wipe_after_stage": True,
            "heading": topic[:80],
            "stages": [],
        },
        "scene3d": {"status": "unavailable", "model": None, "message": MODEL_UNAVAILABLE, "hotspots": []},
        "memory_written": [],
        "listening": dict(LISTENING),
    }
