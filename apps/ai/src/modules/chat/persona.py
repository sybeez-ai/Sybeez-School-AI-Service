"""Persona by role: students talk to "the AI teacher"; staff and parents talk to "the AI assistant"."""

ASSISTANT_OVERRIDE = (
    "\n\nPERSONA OVERRIDE (highest priority): the signed-in user is NOT a student; they are school staff or a parent. "
    'Introduce yourself only as "the AI assistant" and never call yourself "AI teacher". '
    "Speak clearly and professionally to an adult, do not talk to them like a child, and if the product name is said aloud it is pronounced Sy-beez."
)


def is_student(role: str | None) -> bool:
    return (role or "").upper() == "STUDENT"


def assistant_name(role: str | None) -> str:
    """What this person should hear the product call itself."""
    return "AI teacher" if is_student(role) else "AI assistant"


def conversation_title(role: str | None) -> str:
    """Stored chat title. Students keep the existing 'AI Teacher' wording."""
    return "AI Teacher" if is_student(role) else "AI assistant"


def reply_cue(role: str | None) -> str:
    name = assistant_name(role)
    if is_student(role):
        return f"Respond as the {name}."
    return f'Respond as the {name}. Never call yourself "AI teacher".'


def busy_reply(role: str | None) -> str:
    return f"The {assistant_name(role)} could not answer just now. Please try again in a moment."


def persona_system(system: str, role: str | None) -> str:
    """Append the adult-assistant persona for every role except STUDENT."""
    if is_student(role):
        return system
    return system + ASSISTANT_OVERRIDE
