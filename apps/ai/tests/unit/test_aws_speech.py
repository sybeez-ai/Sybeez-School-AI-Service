from types import SimpleNamespace

from src.modules.voice.aws_speech import final_transcript, polly_language


def test_final_transcript_skips_partials_and_keeps_the_language():
    events = [
        SimpleNamespace(
            transcript=SimpleNamespace(
                results=[
                    SimpleNamespace(
                        is_partial=True,
                        language_code="en-IN",
                        alternatives=[SimpleNamespace(transcript="hel")],
                    ),
                    SimpleNamespace(
                        is_partial=False,
                        language_code="hi-IN",
                        alternatives=[SimpleNamespace(transcript="नमस्ते")],
                    ),
                ]
            )
        )
    ]
    text, language = final_transcript(events)
    assert text == "नमस्ते"
    assert language == "hi-IN"


def test_polly_uses_hindi_for_hindi_and_indian_english_otherwise():
    assert polly_language("hi-IN") == "hi-IN"
    assert polly_language("ta") == "en-IN"
    assert polly_language("en") == "en-IN"
