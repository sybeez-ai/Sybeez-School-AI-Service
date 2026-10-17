from src.modules.assets.catalog import clean_regions, library, lookup
from src.providers.gemini_live import build_system_prompt


def test_regions_are_clamped_and_cleaned():
    out = clean_regions([{"label": "Axis", "x": 1.7, "y": -3}, {"label": "", "x": 0, "y": 0}, {"x": 1}, "bad"])
    assert out == [{"label": "Axis", "x": 1.0, "y": 0.0}]
    assert clean_regions(None) == []


def test_lookup_exposes_regions_key_and_library_lists_topics():
    r = lookup("day and night")
    assert r["found"] and all("regions" in i for i in r["images"])
    items = library()
    assert items and {"slug", "title", "subject", "has_3d", "images"} <= set(items[0])


def test_student_prompt_enforces_board_economy_pointing_and_3d():
    p = build_system_prompt("", "elementary", "/student/learning", "student")
    assert "x equals 2" in p and '"x = 2"' in p  # speech verbose, board minimal example
    assert "at most 6 words" in p
    assert "point_at" in p and "glides" in p
    assert "rotate_model" in p and "tab=3d" in p
