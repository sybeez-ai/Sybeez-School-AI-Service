from src.modules.teacher_tools.service import GradeRequest, parse_draft, parse_grade, snap_marks


def req(answer="x", mx=10):
    return GradeRequest(question="What is 2+2?", max_marks=mx, answer=answer)


def test_marks_are_clamped_and_snapped():
    assert snap_marks(11, 10) == 10
    assert snap_marks(-3, 10) == 0
    assert snap_marks(6.7, 10) == 6.5
    assert snap_marks("7", 10) is None
    assert snap_marks(True, 10) is None


def test_grade_always_needs_teacher_review_and_empty_answer_is_zero():
    g = parse_grade({"suggested_marks": 9, "reasoning": "ok", "confidence": "high"}, req(answer="  "))
    assert g.suggested_marks == 0 and g.confidence == "low" and g.needs_teacher_review
    assert parse_grade({"suggested_marks": 5}, req()) is None  # no reasoning: unusable


def test_draft_needs_title_and_sections():
    assert parse_draft({"title": "T", "sections": [{"heading": "Objectives", "body": "b"}]}, "lesson_plan").is_draft
    assert parse_draft({"title": "", "sections": []}, "homework") is None
