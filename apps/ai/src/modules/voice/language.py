"""Shared instruction for live voice and its text fallback.

The model detects the language being spoken and answers in that language.
English is not the default.
"""

VOICE_LANGUAGE = (
    "Detect the language being spoken. When the speaker switches language, switch with them "
    "and reply in that same language. Do not force English."
)
