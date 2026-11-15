"""Amazon Nova 2 Sonic, the one Bedrock voice model.

Chat stays on Nova Lite. Sonic is speech-to-speech and is not offered in
ap-south-1, so the call uses Tokyo (ap-northeast-1), the nearest region that
has it. Voices cover Indian English and Hindi. Tamil and the other Indian
languages are not in Sonic; those narrations stay on Polly until Sonic adds them.
Gemini is not called.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid

logger = logging.getLogger("sybeez.ai.voice.sonic")

MODEL_ID = "amazon.nova-2-sonic-v1:0"
# In-region only. us-east-1, us-west-2, eu-north-1, and ap-northeast-1.
VOICE_REGION = "ap-northeast-1"

# Locales Sonic can speak. kiara and arjun cover en-IN and hi-IN.
_VOICES = {
    "en": "kiara",
    "hi": "kiara",
    "fr": "ambre",
    "it": "beatrice",
    "de": "tina",
    "es": "lupe",
    "pt": "carolina",
}


def sonic_voice(language: str | None) -> str | None:
    short = (language or "en").strip().lower().replace("_", "-").split("-", 1)[0]
    return _VOICES.get(short)


def narration_events(text: str, *, voice_id: str) -> list[dict]:
    """Text in, speech out. The lesson model already wrote the words."""
    prompt = uuid.uuid4().hex
    system = uuid.uuid4().hex
    user = uuid.uuid4().hex
    spoken = " ".join((text or "").split())[:600]
    return [
        {"event": {"sessionStart": {"inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.4}}}},
        {"event": {"promptStart": {
            "promptName": prompt,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 24000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                "audioType": "SPEECH",
            },
        }}},
        {"event": {"contentStart": {
            "promptName": prompt, "contentName": system, "type": "TEXT",
            "interactive": True, "role": "SYSTEM",
            "textInputConfiguration": {"mediaType": "text/plain"},
        }}},
        {"event": {"textInput": {
            "promptName": prompt, "contentName": system,
            "content": "Speak the user's lesson narration exactly. Do not add words.",
        }}},
        {"event": {"contentEnd": {"promptName": prompt, "contentName": system}}},
        {"event": {"contentStart": {
            "promptName": prompt, "contentName": user, "type": "TEXT",
            "interactive": True, "role": "USER",
            "textInputConfiguration": {"mediaType": "text/plain"},
        }}},
        {"event": {"textInput": {"promptName": prompt, "contentName": user, "content": spoken}}},
        {"event": {"contentEnd": {"promptName": prompt, "contentName": user}}},
    ]


def audio_from_events(events: list[dict]) -> bytes:
    chunks: list[bytes] = []
    for event in events:
        body = event.get("event") or event
        audio = (body.get("audioOutput") or {}).get("content")
        if audio:
            chunks.append(base64.b64decode(audio))
    return b"".join(chunks)


def speak_narration(text: str, language: str | None = None) -> bytes | None:
    """PCM 24 kHz from Nova 2 Sonic, or None when this language or the call cannot."""
    voice_id = sonic_voice(language)
    spoken = " ".join((text or "").split())
    if not voice_id or not spoken:
        return None
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        logger.warning("sonic client unavailable")
        return None
    client = boto3.client("bedrock-runtime", region_name=VOICE_REGION)
    method = getattr(client, "invoke_model_with_bidirectional_stream", None)
    if method is None:
        logger.warning("sonic bidirectional stream is not in this boto3 build")
        return None
    events = narration_events(spoken, voice_id=voice_id)
    try:
        response = method(modelId=MODEL_ID, body=[json.dumps(item).encode("utf-8") for item in events])
    except (ClientError, BotoCoreError) as exc:
        code = type(exc).__name__
        if isinstance(exc, ClientError):
            code = str((exc.response.get("Error") or {}).get("Code") or code)
        logger.warning("sonic narration failed: %s", code)
        return None
    raw_events = response.get("events") if isinstance(response, dict) else None
    if not isinstance(raw_events, list):
        logger.warning("sonic narration returned no audio events")
        return None
    audio = audio_from_events(raw_events)
    return audio or None
