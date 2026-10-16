from src.modules.assets import catalog
from src.providers.gemini_live import build_system_prompt

MANIFEST = {
    "version": 1,
    "cdn": "https://cdn.example",
    "models": {"earth-axis": {"url": "https://cdn.example/models/earth-axis.glb", "license": "CC0"}},
    "topics": {
        "day-and-night": {
            "slug": "day-and-night", "title": "Why do we have day and night?", "subject": "Science", "classes": [4],
            "aliases": ["earth rotation"], "key_terms": ["Axis"], "model3d": "earth-axis",
            "images": [{"url": "https://cdn.example/a.jpg", "caption": "c", "alt": "a", "license": "CC BY-SA 4.0",
                        "license_url": "", "author": "x", "source": "https://commons.wikimedia.org/x"}],
        },
        "photosynthesis": {
            "slug": "photosynthesis", "title": "Photosynthesis", "subject": "Science", "classes": [7],
            "aliases": [], "key_terms": [], "model3d": None, "images": [],
        },
    },
}


def use_manifest(monkeypatch):
    monkeypatch.setattr(catalog, "load_manifest", lambda: MANIFEST)


def test_lookup_matches_title_alias_and_returns_s3_urls(monkeypatch):
    use_manifest(monkeypatch)
    for q in ["day and night", "explain earth rotation", "Why do we have day and night?"]:
        r = catalog.lookup(q)
        assert r["found"] and r["source"] == "s3" and r["slug"] == "day-and-night"
        assert r["images"][0]["url"].startswith("https://cdn.example/")
        assert r["model3d"]["url"].endswith("earth-axis.glb")


def test_lookup_never_hotlinks_and_falls_back(monkeypatch):
    use_manifest(monkeypatch)
    r = catalog.lookup("quantum chromodynamics")
    assert r["found"] is False and r["source"] == "placeholder" and r["images"] == []
    assert "wikipedia" not in str(r).lower() and "wikimedia" not in str(r).lower()


def test_portal_prompts():
    student = build_system_prompt("Class: 6", "elementary", "/student/learning", "student")
    assert "Sybeez" in student and "AI Teacher" not in student and "child" in student
    staff = build_system_prompt("", None, "/finance/payroll", "finance")
    assert "Sybeez" in staff and "AI Assistant" not in staff and "confirmed=true" in staff and "child" not in staff
    assert "learning companion" in build_system_prompt("", None, None, "not-a-portal")
