import asyncio

from src.modules.chat.persona import assistant_name, busy_reply, conversation_title, persona_system, reply_cue
from src.modules.voice import agent


def test_names_match_the_portal():
    assert assistant_name("STUDENT") == "AI teacher"
    assert assistant_name("PARENT") == "AI assistant"
    assert conversation_title("STUDENT") == "AI Teacher"
    assert conversation_title("TEACHER") == "AI assistant"
    assert "AI teacher" in reply_cue("STUDENT")
    assert 'Never call yourself "AI teacher"' in reply_cue("SCHOOL_ADMIN")
    assert "AI assistant" in busy_reply("PARENT") and "AI teacher" not in busy_reply("PARENT")
    assert "AI teacher" in busy_reply("STUDENT")


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
