from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.database import tenant_context_statements
from src.core.exceptions import ForbiddenError
from src.core.middleware import client_ip
from src.core.security import AuthContext
from src.db.rls import TENANT_TABLES, rls_sql, tenant_policy_clause
from src.main import app
from src.modules.context.core_client import CoreClient
from src.modules.context.schemas import AuthorizedLearningContext, SchoolContext, StudentContext
from src.modules.context.service import ContextService
from src.modules.memory.repository import MEMORY_VECTOR_SQL, MemoryRepository
from src.modules.practice.schemas import PracticeResponse
from src.modules.retrieval.repository import KNOWLEDGE_VECTOR_SQL, RetrievalRepository
from src.shared.vector import vector_literal
from tests.security.jwks import SCHOOL_A, SCHOOL_B, USER_A, USER_B, bearer, mint

client = TestClient(app)


def test_set_local_uses_bound_token_identity():
    statements = tenant_context_statements(SCHOOL_A, USER_A)
    assert statements[0] == (
        "SELECT set_config('app.school_id', :school_id, true)",
        {"school_id": str(SCHOOL_A)},
    )
    assert statements[1] == (
        "SELECT set_config('app.user_id', :user_id, true)",
        {"user_id": str(USER_A)},
    )
    assert str(SCHOOL_B) not in statements[0][0]
    assert ", true)" in statements[0][0]


def test_rls_policies_cover_every_tenant_table():
    sql = rls_sql()
    clause = tenant_policy_clause()
    assert "app.school_id" in clause
    for table in TENANT_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in sql
        assert f"CREATE POLICY {table}_tenant_isolation" in sql
    assert sql.count(clause) >= len(TENANT_TABLES) * 2


def test_vector_sql_is_school_scoped():
    sql = str(KNOWLEDGE_VECTOR_SQL)
    assert "school_id = CAST(:school_id AS uuid)" in sql
    assert "embedding <=>" in sql
    memory_sql = str(MEMORY_VECTOR_SQL)
    assert "school_id = CAST(:school_id AS uuid)" in memory_sql
    assert "student_id = CAST(:student_id AS uuid)" in memory_sql


def test_embedding_literal_rejects_injection():
    literal = vector_literal([0.25, 1])
    assert "'" not in literal
    assert ";" not in literal
    with pytest.raises(ValueError):
        vector_literal(["1); DELETE FROM knowledge_chunks;--"])


class _Result:
    def __init__(self, rows=None, scalars=None):
        self._rows = rows or []
        self._scalars = scalars or []

    def fetchall(self):
        return self._rows

    def scalars(self):
        return self

    def all(self):
        return self._scalars


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDb:
    def __init__(self):
        self.calls = []
        self.vector_rows = []
        self.orm_rows = []
        self.chunks = {}
        self.vector_error = False

    def begin_nested(self):
        return _Nested()

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "<=>" in sql:
            if self.vector_error:
                raise RuntimeError("pgvector missing")
            return _Result(rows=self.vector_rows)
        return _Result(scalars=self.orm_rows)

    async def get(self, model, ident):
        return self.chunks.get(ident)


def _chunk(school_id, content):
    return SimpleNamespace(id=uuid4(), school_id=school_id, content=content, document_id=uuid4())


async def test_vector_search_drops_other_school_rows():
    own = _chunk(SCHOOL_A, "own lesson")
    other = _chunk(SCHOOL_B, "other school secret")
    db = FakeDb()
    db.vector_rows = [
        SimpleNamespace(id=own.id, school_id=SCHOOL_A, score=0.4),
        SimpleNamespace(id=other.id, school_id=SCHOOL_B, score=0.99),
    ]
    db.chunks = {own.id: own, other.id: other}
    rows = await RetrievalRepository(db).similarity_search(school_id=SCHOOL_A, embedding=[0.1, 0.2], limit=100)
    assert [chunk.content for chunk, _score in rows] == ["own lesson"]
    sql, params = db.calls[0]
    assert str(SCHOOL_A) not in sql
    assert params["school_id"] == str(SCHOOL_A)
    assert params["limit"] == 20


async def test_vector_failure_fallback_stays_inside_school():
    own = _chunk(SCHOOL_A, "own lesson")
    other = _chunk(SCHOOL_B, "other school secret")
    db = FakeDb()
    db.vector_error = True
    db.orm_rows = [other, own]
    rows = await RetrievalRepository(db).similarity_search(school_id=SCHOOL_A, embedding=[0.1, 0.2])
    assert [chunk.content for chunk, _score in rows] == ["own lesson"]


async def test_memory_vector_drops_other_school_and_student():
    mine = SimpleNamespace(id=uuid4(), school_id=SCHOOL_A, student_id=USER_A, content="mine", memory_type="concept")
    theirs = SimpleNamespace(id=uuid4(), school_id=SCHOOL_B, student_id=USER_B, content="theirs", memory_type="concept")
    classmate = SimpleNamespace(
        id=uuid4(), school_id=SCHOOL_A, student_id=USER_B, content="classmate", memory_type="concept"
    )
    db = FakeDb()
    db.vector_rows = [
        SimpleNamespace(id=mine.id, school_id=SCHOOL_A, student_id=USER_A, score=0.2),
        SimpleNamespace(id=theirs.id, school_id=SCHOOL_B, student_id=USER_B, score=0.99),
        SimpleNamespace(id=classmate.id, school_id=SCHOOL_A, student_id=USER_B, score=0.8),
    ]
    db.chunks = {mine.id: mine, theirs.id: theirs, classmate.id: classmate}
    found = await MemoryRepository(db).similarity_search(
        school_id=SCHOOL_A, student_id=USER_A, embedding=[0.2, 0.3]
    )
    assert [row.content for row in found] == ["mine"]
    _sql, params = db.calls[0]
    assert params["school_id"] == str(SCHOOL_A)
    assert params["student_id"] == str(USER_A)


async def test_memory_list_post_filters_tenant():
    mine = SimpleNamespace(id=uuid4(), school_id=SCHOOL_A, student_id=USER_A, content="mine")
    theirs = SimpleNamespace(id=uuid4(), school_id=SCHOOL_B, student_id=USER_B, content="theirs")
    db = FakeDb()
    db.orm_rows = [theirs, mine]
    found = await MemoryRepository(db).list_recent(school_id=SCHOOL_A, student_id=USER_A)
    assert [row.content for row in found] == ["mine"]


def test_client_headers_cannot_override_token_tenant(monkeypatch):
    captured = {}

    async def fake_generate(self, auth, body, bearer_token=None):
        captured["school_id"] = auth.school_id
        captured["user_id"] = auth.user_id
        captured["role"] = auth.role
        return PracticeResponse(topic="t", difficulty="adaptive", questions=[])

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", fake_generate)
    response = client.post(
        "/api/v1/ai/practice",
        headers={
            **bearer(mint()),
            "X-School-Id": str(SCHOOL_B),
            "X-User-Id": str(USER_B),
            "X-Role": "PLATFORM_ADMIN",
        },
        json={"count": 1, "school_id": str(SCHOOL_B), "user_id": str(USER_B), "role": "PLATFORM_ADMIN"},
    )
    assert response.status_code == 200
    assert captured["school_id"] == SCHOOL_A
    assert captured["user_id"] == USER_A
    assert captured["role"] == "STUDENT"


def test_database_context_comes_from_token(monkeypatch):
    captured = {}

    class Dummy:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    def fake_install(session, *, school_id, user_id):
        captured["school_id"] = school_id
        captured["user_id"] = user_id

    async def fake_list(self, auth):
        captured["auth_school"] = auth.school_id
        captured["auth_user"] = auth.user_id
        return []

    monkeypatch.setattr("src.api.dependencies.AsyncSessionLocal", lambda: Dummy())
    monkeypatch.setattr("src.api.dependencies.install_tenant_context", fake_install)
    monkeypatch.setattr("src.modules.conversations.router.ConversationService.list", fake_list)
    response = client.get(
        "/api/v1/ai/conversations",
        headers={**bearer(mint()), "X-School-Id": str(SCHOOL_B), "X-User-Id": str(USER_B)},
    )
    assert response.status_code == 200
    assert response.json() == []
    assert captured["school_id"] == SCHOOL_A
    assert captured["user_id"] == USER_A
    assert captured["auth_school"] == SCHOOL_A
    assert captured["auth_user"] == USER_A


async def test_core_context_school_must_match_token(monkeypatch):
    async def fake_context(self, **kwargs):
        return AuthorizedLearningContext(student=StudentContext(id=USER_A), school=SchoolContext(id=SCHOOL_B))

    monkeypatch.setattr(CoreClient, "get_ai_context", fake_context)
    auth = AuthContext(user_id=USER_A, role="STUDENT", school_id=SCHOOL_A, membership_id=None, raw={})
    with pytest.raises(ForbiddenError):
        await ContextService().for_user(auth)


def test_untrusted_proxy_ignores_forwarded_for():
    scope = {"headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.8")], "client": ("10.9.9.9", 1)}
    assert client_ip(scope) == "10.9.9.9"
