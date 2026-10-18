import asyncio

from src.modules.chat.persona import persona_system
from src.modules.voice import agent


def test_students_keep_the_ai_teacher_persona():
    assert persona_system("BASE", "STUDENT") == "BASE"


def test_staff_and_parents_get_the_ai_assistant_persona():
    for role in ("TEACHER", "SCHOOL_ADMIN", "PARENT", None):
        out = persona_system("BASE", role)
        assert out.startswith("BASE") and "AI assistant" in out and 'never call yourself "AI teacher"' in out


class _Echo:
    async def complete(self, *, system, user):
        return system


def test_text_fallback_uses_assistant_prompt_for_non_students():
    system = asyncio.run(agent.text_answer(_Echo(), message="hi", student=False))
    assert "AI assistant" in system and "child" not in system.lower()
    system = asyncio.run(agent.text_answer(_Echo(), message="hi", student=True))
    assert "AI teacher" in system
