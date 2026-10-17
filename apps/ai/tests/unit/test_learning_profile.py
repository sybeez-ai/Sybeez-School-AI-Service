from uuid import uuid4

from fastapi.testclient import TestClient

from src.db.rls import profile_rls_sql
from src.main import app
from src.modules.profile import logic
from tests.security.jwks import bearer, mint

client = TestClient(app)


def _outcomes(p, style, topic, results):
    for ok in results:
        p = logic.apply_event(p, {"kind": "outcome", "style": style, "topic": topic, "correct": ok})
    return p


def test_best_style_needs_evidence_and_adapts():
    p = logic.empty_profile()
    assert logic.best_style(p) is None and logic.prompt_block(p) == ""
    p = _outcomes(p, "visual", "fractions", [True, True, True, True])
    p = _outcomes(p, "stories", "fractions", [False, False, True])
    assert logic.best_style(p) == "visual"
    assert "pictures, diagrams and 3D views" in logic.prompt_block(p)


def test_weak_topics_and_corrections():
    p = _outcomes(None, "step_by_step", "Photosynthesis", [False, False, True])
    assert [w["topic"] for w in logic.weak_topics(p)] == ["photosynthesis"]
    q = logic.correct(p, style_override="stories", clear_style=False, dismiss_topics=["Photosynthesis"])
    assert logic.weak_topics(q) == [] and logic.best_style(q) == "stories"
    assert logic.correct(q, style_override=None, clear_style=True, dismiss_topics=[])["style_override"] is None
    rep = logic.report(q)
    assert "retention" in rep and rep["summary"]


def test_speaking_reading_and_bad_events():
    p = logic.apply_event(None, {"kind": "speaking", "minutes": 5})
    p = logic.apply_event(p, {"kind": "reading", "pages": 3})
    p = logic.apply_event(p, {"kind": "nonsense"})
    assert p["speaking"]["sessions"] == 1 and p["reading"]["pages"] == 3
    assert "conversation text" in logic.RETENTION


def test_rls_policy_is_tenant_and_audience_scoped():
    sql = profile_rls_sql()
    assert "FORCE ROW LEVEL SECURITY" in sql and "app.school_id" in sql
    assert "ANY(guardian_user_ids)" in sql and "ANY(teacher_user_ids)" in sql
    assert "WITH CHECK" in sql and "student_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);" in sql


def test_endpoint_authz():
    sid = uuid4()
    assert client.get("/api/v1/ai/profile/me").status_code == 401
    assert client.get(f"/api/v1/ai/profile/student/{sid}", headers=bearer(mint())).status_code == 403
    assert client.get("/api/v1/ai/profile/me", headers=bearer(mint(role="PARENT"))).status_code == 403
    assert client.get(f"/api/v1/ai/profile/student/{sid}", headers=bearer(mint(role="SCHOOL_ADMIN"))).status_code == 403
    ev = {"kind": "outcome", "topic": "x", "correct": True}
    assert client.post("/api/v1/ai/profile/events", json=ev, headers=bearer(mint(role="TEACHER"))).status_code == 403
    assert client.delete("/api/v1/ai/profile/me", headers=bearer(mint(role="PARENT"))).status_code == 403
