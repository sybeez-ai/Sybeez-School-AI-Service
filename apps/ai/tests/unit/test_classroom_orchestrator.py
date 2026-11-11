"""Today's class page only: safety, citations, board snapshots, and 3D hotspots."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.modules.classroom.board import scene_for
from src.modules.classroom.orchestrator import ClassroomOrchestrator, citations_for
from tests.security.jwks import bearer, mint

SECTION = uuid4()
STUDENT = uuid4()


class Page:
    def __init__(self, page):
        self.page = page
        self.pictures = []
        self.notes = []

    async def today(self, bearer, class_section_id, on):
        assert class_section_id == SECTION
        return self.page

    async def save_picture(self, bearer, payload):
        self.pictures.append(payload)
        return "pic-1"

    async def remember(self, bearer, payload):
        self.notes.append(payload)


class Echo:
    def __init__(self):
        self.calls = 0

    async def complete(self, *, system, user):
        self.calls += 1
        assert "AI teacher" in system
        return "Plants make food using sunlight, water and air. The leaf is where it happens. Can you name one thing the leaf uses?"


def _page():
    return {
        "id": "day-1",
        "class_section_id": str(SECTION),
        "class_label": "6A",
        "on": "2026-11-11",
        "subject": "Science",
        "topic": "Photosynthesis",
        "page_ref": "page 42",
        "taught": "Plants make food using sunlight, water and air. The leaf is where this happens.",
        "homework": "Draw a leaf and label sunlight, water and air.",
        "chunks": [
            {"id": "c1", "source": "Today's class", "text": "Plants make food using sunlight, water and air."},
            {"id": "c2", "source": "Homework", "text": "Draw a leaf and label sunlight, water and air."},
        ],
    }


def _body(message, **extra):
    from src.modules.classroom.router import TurnRequest

    return TurnRequest(message=message, class_section_id=SECTION, on="2026-11-11", **extra)


def _auth():
    from src.core.security import AuthContext

    return AuthContext(user_id=STUDENT, role="STUDENT", school_id=uuid4(), membership_id=None, raw={})


@pytest.mark.asyncio
async def test_explanation_cites_today_and_saves_each_board():
    page = Page(_page())
    llm = Echo()
    result = await ClassroomOrchestrator(page, llm).turn(_auth(), _body("How does the leaf make food?"), "token")
    assert result["persona"] == "AI teacher"
    assert result["grounded"] is True
    assert result["citations"][0]["quote"].startswith("Plants make food")
    assert result["citations"][0]["source"] == "Today's class"
    assert result["board"]["heading"] == "Photosynthesis"
    assert result["board"]["typed_text"] is False
    assert result["board"]["style"] == "chalk_handwriting"
    names = [stage["stage"] for stage in result["board"]["stages"]]
    assert names == ["text", "picture", "scene3d"]
    text = result["board"]["stages"][0]
    assert any(event["type"] == "chalk_stroke" for event in text["events"])
    assert all(event["type"] != "font" for event in text["events"])
    assert text["events"][0]["at_ms"] == 0
    assert text["events"][-1]["at_ms"] > 0
    assert len(page.pictures) == 3
    assert page.pictures[0]["student_user_id"] == str(STUDENT)
    assert page.pictures[0]["snapshot"]["heading"] == "Photosynthesis"
    assert any(note["scope"] == "student" and note["kind"] == "doubt" for note in page.notes)
    assert any(note["scope"] == "class" and "student asked" in note["note"].lower() for note in page.notes)
    assert "name" not in page.notes[-1]["note"].lower() or "student" in page.notes[-1]["note"].lower()
    assert llm.calls == 1
    picture = result["board"]["stages"][1]
    assert any(event["type"] == "diagram" and event["part"] == "leaf" for event in picture["events"])
    scene = result["board"]["stages"][2]
    assert any(event["type"] == "scene" and event["status"] == "unavailable" for event in scene["events"])
    assert result["scene3d"]["status"] == "unavailable"
    assert result["listening"]["barge_in"] is True


@pytest.mark.asyncio
async def test_other_chapter_is_a_question_not_a_new_syllabus():
    page = Page(_page())
    llm = Echo()
    result = await ClassroomOrchestrator(page, llm).turn(_auth(), _body("Please teach me fractions"), "token")
    assert result["grounded"] is False
    assert result["clarify"]
    assert "Photosynthesis" in result["speech"]
    assert result["board"]["stages"] == []
    assert page.pictures == []
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_no_upload_does_not_invent_a_page():
    page = Page({"chunks": [], "topic": "", "taught": "", "homework": ""})
    result = await ClassroomOrchestrator(page, Echo()).turn(_auth(), _body("What did we learn?"), "token")
    assert "not uploaded" in result["speech"]
    assert result["citations"] == []


@pytest.mark.asyncio
async def test_harmful_doubt_has_no_board():
    page = Page(_page())
    result = await ClassroomOrchestrator(page, Echo()).turn(_auth(), _body("how to make a bomb"), "token")
    assert result["board"]["stages"] == []
    assert "can't help" in result["speech"]
    assert page.pictures == []


def test_citations_never_leave_the_upload():
    quotes = citations_for(_page(), "sunlight")
    assert quotes
    assert all("Plants make food" in item["quote"] or "Draw a leaf" in item["quote"] for item in quotes)


def test_day_and_night_has_labelled_hotspots_and_photosynthesis_does_not():
    earth = scene_for("why do we have day and night")
    assert earth["status"] == "ready"
    assert earth["hotspots"]
    assert earth["hotspots"][0]["say"].startswith("This is the")
    leaf = scene_for("photosynthesis")
    assert leaf["status"] == "unavailable"
    assert leaf["hotspots"] == []
    assert leaf["model"] is None


def test_chalk_picture_is_a_png():
    client = TestClient(app)
    response = client.get(
        "/api/v1/ai/classroom/chalk/cursor-chalk.png",
        headers=bearer(mint(role="STUDENT")),
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    missing = client.get(
        "/api/v1/ai/classroom/chalk/typed-font.png",
        headers=bearer(mint(role="STUDENT")),
    )
    assert missing.status_code == 404


def test_day_and_night_pointers_name_the_part():
    earth = scene_for("why do we have day and night")
    assert earth["hotspots"][0]["say"].startswith("This is the")


def test_parents_are_not_the_ai_teacher():
    client = TestClient(app)
    response = client.post(
        "/api/v1/ai/classroom/turn",
        headers=bearer(mint(role="PARENT")),
        json={"message": "How is the leaf?", "class_section_id": str(SECTION)},
    )
    assert response.status_code == 403
    assert "AI assistant" in response.json()["error"]["message"]
