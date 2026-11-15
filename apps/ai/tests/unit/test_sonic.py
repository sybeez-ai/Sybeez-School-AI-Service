"""Nova 2 Sonic event shape. No network call."""

import base64

from src.modules.voice.sonic import audio_from_events, narration_events, sonic_voice


def test_indian_english_and_hindi_use_sonic_and_tamil_does_not():
    assert sonic_voice("en") == "kiara"
    assert sonic_voice("hi-IN") == "kiara"
    assert sonic_voice("ta") is None
    assert sonic_voice("te") is None


def test_narration_is_text_in_and_names_the_voice():
    events = narration_events("The cat sat.", voice_id="kiara")
    names = [next(iter(item["event"])) for item in events]
    assert names[0] == "sessionStart"
    assert names[1] == "promptStart"
    assert events[1]["event"]["promptStart"]["audioOutputConfiguration"]["voiceId"] == "kiara"
    assert events[-2]["event"]["textInput"]["content"] == "The cat sat."
    assert names[-1] == "contentEnd"


def test_audio_events_become_pcm():
    payload = base64.b64encode(b"pcm").decode("ascii")
    audio = audio_from_events([{"event": {"audioOutput": {"content": payload}}}])
    assert audio == b"pcm"
