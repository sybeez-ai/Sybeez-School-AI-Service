"""POST /api/v1/ai/voice/transcribe sends audio to Amazon Transcribe, not Gemini or Qwen ASR."""

from fastapi.testclient import TestClient

from src.core.exceptions import UpstreamError
from src.main import app
from src.modules.voice import aws_speech
from src.modules.voice.transcribe import detect_language, parse_transcript
from tests.security.jwks import bearer, mint

client = TestClient(app)
PATH = "/api/v1/ai/voice/transcribe"


def test_language_code_follows_the_script():
    assert detect_language("hello") == "en"
    assert detect_language("வணக்கம்") == "ta"
    assert detect_language("नमस्ते") == "hi"
    text, language = parse_transcript('{"text": "வணக்கம்", "language": "ta"}')
    assert text == "வணக்கம்" and language == "ta"
    text, language = parse_transcript("plain english words")
    assert language == "en"


def test_transcribe_requires_auth_and_rejects_empty_audio():
    assert client.post(PATH).status_code == 401
    empty = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"", "audio/webm")})
    assert empty.status_code == 400
    assert empty.json()["error"]["message"] == "Audio is empty"
    assert "Traceback" not in empty.text


def test_transcribe_uses_amazon_transcribe(monkeypatch):
    called = {"count": 0}

    async def clip(audio: bytes, mime: str | None):
        called["count"] += 1
        assert audio
        assert mime == "audio/webm"
        return "good morning", "en-IN"

    async def published(*_args, **_kwargs):
        return None

    monkeypatch.setattr(aws_speech, "transcribe_clip", clip)
    monkeypatch.setattr("src.modules.voice.router.publish_usage", published)
    response = client.post(
        PATH,
        headers=bearer(mint()),
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "good morning"
    assert response.json()["language"] == "en"
    assert called["count"] == 1
    assert "gemini" not in response.text.lower()


def test_transcribe_failure_is_a_clear_error(monkeypatch):
    async def clip(_audio: bytes, _mime: str | None):
        raise UpstreamError("Could not transcribe the audio")

    monkeypatch.setattr(aws_speech, "transcribe_clip", clip)
    response = client.post(PATH, headers=bearer(mint()), files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Could not transcribe the audio"
    assert "Traceback" not in response.text
