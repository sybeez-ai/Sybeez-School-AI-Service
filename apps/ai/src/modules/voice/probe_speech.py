"""Probe DashScope speech models with the task's key. Prints status codes only.

The key, audio, and response bodies are not printed. Run inside the AI task:

    python -m src.modules.voice.probe_speech
"""

from __future__ import annotations

import json
import math
import os
import struct
import urllib.error
import urllib.request
import wave
from io import BytesIO

INTL = "https://dashscope-intl.aliyuncs.com"
CN = "https://dashscope.aliyuncs.com"


def _tone() -> str:
    import base64

    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(16000)
        )
        handle.writeframes(frames)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _post(url: str, key: str, body: dict) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(400)
            return response.status, _code(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read(400)
        return exc.code, _code(raw)


def _code(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    code = payload.get("code") or ""
    if not code and isinstance(payload.get("error"), dict):
        code = payload["error"].get("code") or payload["error"].get("message") or ""
    text = str(code).replace("\n", " ")
    return text[:80]


def main() -> None:
    key = os.environ.get("QWEN_API_KEY") or os.environ.get("QWEN_CHAT_API_KEY") or ""
    print(f"key_present={bool(key)} key_len={len(key)}")
    if not key:
        return
    encoded = _tone()
    asr = [
        ("intl-chat", f"{INTL}/compatible-mode/v1/chat/completions", "qwen3-asr-flash", "chat"),
        ("intl-mm", f"{INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen2-audio-instruct", "mm"),
        ("intl-mm", f"{INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen-audio-turbo", "mm"),
        ("intl-chat", f"{INTL}/compatible-mode/v1/chat/completions", "qwen2.5-omni-7b", "chat"),
        ("intl-chat", f"{INTL}/compatible-mode/v1/chat/completions", "qwen-omni-turbo", "chat"),
        ("intl-mm", f"{INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-asr-flash", "mm"),
        ("cn-chat", f"{CN}/compatible-mode/v1/chat/completions", "qwen3-asr-flash", "chat"),
        ("cn-mm", f"{CN}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-asr-flash", "mm"),
    ]
    tts = [
        ("intl-speech", f"{INTL}/compatible-mode/v1/audio/speech", "qwen3-tts-flash", "speech"),
        ("intl-mm", f"{INTL}/api/v1/services/aigc/multimodal-generation/generation", "qwen3-tts-flash", "tts"),
        ("cn-speech", f"{CN}/compatible-mode/v1/audio/speech", "qwen3-tts-flash", "speech"),
    ]
    for name, url, model, shape in asr:
        if shape == "chat":
            body = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
                            {"type": "text", "text": "Transcribe."},
                        ],
                    }
                ],
            }
        else:
            body = {
                "model": model,
                "input": {"messages": [{"role": "user", "content": [{"audio": f"data:audio/wav;base64,{encoded}"}]}]},
                "parameters": {"asr_options": {"enable_lid": True}},
            }
        status, code = _post(url, key, body)
        print(f"asr host={name} model={model} status={status} code={code}")
    for name, url, model, shape in tts:
        if shape == "speech":
            body = {"model": model, "input": "Hello", "voice": "Cherry"}
        else:
            body = {"model": model, "input": {"text": "Hello", "voice": "Cherry", "language_type": "Auto"}}
        status, code = _post(url, key, body)
        print(f"tts host={name} model={model} status={status} code={code}")


if __name__ == "__main__":
    main()
