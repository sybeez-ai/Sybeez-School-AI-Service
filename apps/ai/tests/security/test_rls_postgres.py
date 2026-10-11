"""Live Postgres proof of the school RLS predicate. Skips when no database is up."""

import os

import psycopg2
import pytest

from src.db.rls import tenant_policy_clause

_URLS = [
    os.environ.get("DATABASE_URL_SYNC") or "",
    "postgresql://sybeez:sybeez@localhost:5432/sybeez",
    "postgresql://sybeez:sybeez@localhost:5432/sybeez_school",
]


def _connect():
    for url in _URLS:
        if not url or url.startswith("postgresql+"):
            continue
        try:
            return psycopg2.connect(url, connect_timeout=2)
        except Exception:
            continue
    return None


@pytest.fixture
def pg_conn():
    connection = _connect()
    if connection is None:
        pytest.skip("Postgres is not available")
    try:
        yield connection
    finally:
        connection.close()


def test_set_local_does_not_leak_to_the_next_transaction(pg_conn):
    school = "11111111-1111-1111-1111-111111111111"
    pg_conn.autocommit = False
    with pg_conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.school_id', %s, true)", (school,))
        cursor.execute("SELECT current_setting('app.school_id', true)")
        assert cursor.fetchone()[0] == school
    pg_conn.rollback()
    with pg_conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.school_id', true)")
        assert cursor.fetchone()[0] in ("", None)


def test_rls_predicate_hides_other_schools(pg_conn):
    clause = tenant_policy_clause()
    role = "sybeez_ai_rls_test"
    school_a = "11111111-1111-1111-1111-111111111111"
    school_b = "22222222-2222-2222-2222-222222222222"
    pg_conn.autocommit = True
    with pg_conn.cursor() as cursor:
        cursor.execute(
            f"""
            DO $$ BEGIN
                CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOLOGIN;
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    pg_conn.autocommit = False
    try:
        with pg_conn.cursor() as cursor:
            cursor.execute("CREATE TABLE rls_probe (id int, school_id uuid, content text)")
            cursor.execute("ALTER TABLE rls_probe ENABLE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE rls_probe FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY rls_probe_tenant_isolation ON rls_probe USING ({clause}) WITH CHECK ({clause})"
            )
            cursor.execute(f"GRANT SELECT, INSERT ON rls_probe TO {role}")
            cursor.execute("SELECT set_config('app.school_id', %s, true)", (school_a,))
            cursor.execute("INSERT INTO rls_probe VALUES (1, %s, 'alpha')", (school_a,))
            cursor.execute("SELECT set_config('app.school_id', %s, true)", (school_b,))
            cursor.execute("INSERT INTO rls_probe VALUES (2, %s, 'beta')", (school_b,))
            cursor.execute(f"SET LOCAL ROLE {role}")
            cursor.execute("SELECT set_config('app.school_id', %s, true)", (school_a,))
            cursor.execute("SELECT content FROM rls_probe ORDER BY id")
            assert cursor.fetchall() == [("alpha",)]
            cursor.execute("SELECT set_config('app.school_id', %s, true)", (school_b,))
            cursor.execute("SELECT content FROM rls_probe ORDER BY id")
            assert cursor.fetchall() == [("beta",)]
            cursor.execute("SELECT set_config('app.school_id', '', true)")
            cursor.execute("SELECT content FROM rls_probe")
            assert cursor.fetchall() == []
        pg_conn.rollback()
    finally:
        pg_conn.rollback()
