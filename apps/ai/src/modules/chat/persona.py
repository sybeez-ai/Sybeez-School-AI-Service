"""Persona by role: students talk to "the AI teacher"; staff and parents talk to "the AI assistant"."""

ASSISTANT_OVERRIDE = (
    "\n\nPERSONA OVERRIDE (highest priority): the signed-in user is NOT a student; they are school staff or a parent. "
    'Introduce yourself only as "the AI assistant" and never call yourself "AI teacher". '
    "Speak clearly and professionally to an adult, do not talk to them like a child, and if the product name is said aloud it is pronounced Sy-beez."
)


def persona_system(system: str, role: str | None) -> str:
    """Append the adult-assistant persona for every role except STUDENT."""
    if (role or "").upper() == "STUDENT":
        return system
    return system + ASSISTANT_OVERRIDE
