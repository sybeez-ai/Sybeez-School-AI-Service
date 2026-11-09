"""Board heading, 3D, and picture choices stay on the topic the student just asked for."""

from src.modules.assets.catalog import MODEL_UNAVAILABLE, lookup
from src.modules.teacher.graph import asks_for_new_topic
from src.modules.teacher.heading import align_board_heading
from src.modules.teacher.images import image_from_wikimedia, image_ok_for_class, kid_search_query, too_technical
from src.modules.voice.agent import trim_student_tools


def test_new_topic_replaces_the_old_board_heading():
    actions = align_board_heading(
        [{"type": "write_text", "page_id": "old", "text": "Sunlight + water + air"}],
        "Photosynthesis",
        previous_title="Why do we have day and night?",
    )
    assert actions[0]["type"] == "new_page"
    assert actions[0]["title"] == "Photosynthesis"
    assert actions[1]["page_id"] == actions[0]["page_id"]
    assert all(item.get("title") != "Why do we have day and night?" for item in actions)


def test_same_topic_does_not_open_another_page():
    actions = [{"type": "write_text", "page_id": "current", "text": "Day side"}]
    assert align_board_heading(actions, "Why do we have day and night?", previous_title="Why do we have day and night?") == actions


def test_photosynthesis_is_a_new_topic_and_a_short_answer_is_not():
    plan = {"topic": "Why do we have day and night?"}
    assert asks_for_new_topic("Start a lesson on photosynthesis", plan)
    assert not asks_for_new_topic("the night side", plan)
    assert not asks_for_new_topic("explain that again", plan)


def test_class_6_photosynthesis_drops_the_c4_diagram_and_has_no_3d():
    result = lookup("photosynthesis", class_no=6)
    assert result["found"] and result["slug"] == "photosynthesis"
    assert result["title"] == "Photosynthesis"
    assert result["model3d"] is None
    assert result["model3d_status"] == "unavailable"
    assert result["model3d_message"] == MODEL_UNAVAILABLE
    blob = " ".join(
        f"{image.get('caption', '')} {image.get('alt', '')} {image.get('source', '')}" for image in result["images"]
    )
    assert "c4" not in blob.lower()
    assert not too_technical(blob)


def test_day_and_night_keeps_its_own_3d_model():
    result = lookup("why do we have day and night", class_no=6)
    assert result["model3d"]["name"] == "earth-axis"
    assert result["model3d_status"] == "ready"
    assert result["model3d_message"] is None


def test_unknown_topic_does_not_borrow_the_earth_model():
    result = lookup("quantum chromodynamics")
    assert result["model3d"] is None
    assert result["model3d_message"] == MODEL_UNAVAILABLE


def test_technical_commons_file_is_skipped_for_younger_students():
    payload = {
        "query": {
            "pages": [
                {
                    "title": "File:C4 photosynthesis is really complicated.svg",
                    "imageinfo": [{"mime": "image/svg+xml", "thumburl": "https://upload.wikimedia.org/wikipedia/commons/c4.png"}],
                },
                {
                    "title": "File:Photosynthesis simple diagram.svg",
                    "imageinfo": [{"mime": "image/svg+xml", "thumburl": "https://upload.wikimedia.org/wikipedia/commons/simple.png"}],
                },
            ]
        }
    }
    assert image_from_wikimedia(payload).endswith("simple.png")
    assert not image_ok_for_class({"caption": "C4 photosynthesis is less complicated", "source": "File:C4.svg"}, 6)
    assert image_ok_for_class({"caption": "A leaf in sunlight", "source": "leaf.svg"}, 6)
    assert kid_search_query("photosynthesis", 6).endswith("simple labelled diagram for kids")
    assert "for kids" not in kid_search_query("photosynthesis", 10)


def test_voice_turn_drops_the_earth_model_for_photosynthesis():
    calls = [
        {"function": {"name": "show_earth_3d", "arguments": "{}"}},
        {"function": {"name": "show_picture", "arguments": "{\"query\":\"photosynthesis\"}"}},
        {"function": {"name": "observe_page", "arguments": "{}"}},
    ]
    kept, dropped = trim_student_tools(calls, topic_text="Start a lesson on photosynthesis", already_used=0)
    assert dropped is True
    assert [call["function"]["name"] for call in kept] == ["show_picture"]
    assert trim_student_tools(calls, topic_text="photosynthesis", already_used=1) == ([], False)


def test_voice_turn_keeps_earth_3d_for_day_and_night():
    calls = [{"function": {"name": "show_earth_3d", "arguments": "{}"}}]
    kept, dropped = trim_student_tools(calls, topic_text="why do we have day and night", already_used=0)
    assert dropped is False
    assert kept[0]["function"]["name"] == "show_earth_3d"
