"""School-scoped row level security for AI-owned tables.

Policies compare school_id to the transaction-local GUC app.school_id, which the
API sets from the verified token. app.user_id is set in the same transaction.
Knowledge rows are shared inside a school. Teacher-session policies also require
the current user to be the student or a linked parent or teacher.
"""

TENANT_TABLES: tuple[str, ...] = (
    "ai_conversations",
    "ai_messages",
    "student_ai_memory",
    "knowledge_documents",
    "knowledge_chunks",
)


def tenant_policy_clause() -> str:
    return "school_id = NULLIF(current_setting('app.school_id', true), '')::uuid"


def rls_sql() -> str:
    clause = tenant_policy_clause()
    statements: list[str] = []
    for table in TENANT_TABLES:
        statements.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        statements.append(
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};"
        )
        statements.append(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({clause}) WITH CHECK ({clause});"
        )
    return "\n".join(statements)


def rls_downgrade_sql() -> str:
    statements: list[str] = []
    for table in TENANT_TABLES:
        statements.append(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        statements.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return "\n".join(statements)


TEACHER_SESSION_TABLE = "teacher_sessions"
TEACHER_CHILD_TABLES: tuple[str, ...] = (
    "teacher_lesson_plans",
    "teacher_board_pages",
    "teacher_board_actions",
    "teacher_messages",
    "teacher_progress",
)


def _user_uuid() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def teacher_session_using_sql() -> str:
    """Student, linked parent, or linked teacher, inside the token school."""
    user = _user_uuid()
    return (
        f"{tenant_policy_clause()} AND ("
        f"student_user_id = {user} OR "
        f"{user} = ANY(guardian_user_ids) OR "
        f"{user} = ANY(teacher_user_ids))"
    )


def teacher_session_check_sql() -> str:
    """Only the student writes the session row."""
    return f"{tenant_policy_clause()} AND student_user_id = {_user_uuid()}"


def _child_exists(table: str, *, write: bool) -> str:
    user = _user_uuid()
    audience = (
        f"s.student_user_id = {user}"
        if write
        else (
            f"(s.student_user_id = {user} OR {user} = ANY(s.guardian_user_ids) "
            f"OR {user} = ANY(s.teacher_user_ids))"
        )
    )
    return (
        f"{tenant_policy_clause()} AND EXISTS ("
        f"SELECT 1 FROM {TEACHER_SESSION_TABLE} s "
        f"WHERE s.id = {table}.session_id AND s.school_id = {table}.school_id AND {audience})"
    )


def teacher_rls_sql() -> str:
    statements: list[str] = []
    tables = (TEACHER_SESSION_TABLE, *TEACHER_CHILD_TABLES)
    for table in tables:
        statements.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        statements.append(f"DROP POLICY IF EXISTS {table}_audience ON {table};")
    statements.append(
        f"CREATE POLICY {TEACHER_SESSION_TABLE}_audience ON {TEACHER_SESSION_TABLE} "
        f"USING ({teacher_session_using_sql()}) WITH CHECK ({teacher_session_check_sql()});"
    )
    for table in TEACHER_CHILD_TABLES:
        statements.append(
            f"CREATE POLICY {table}_audience ON {table} "
            f"USING ({_child_exists(table, write=False)}) WITH CHECK ({_child_exists(table, write=True)});"
        )
    return "\n".join(statements)


def teacher_rls_downgrade_sql() -> str:
    statements: list[str] = []
    for table in (TEACHER_SESSION_TABLE, *TEACHER_CHILD_TABLES):
        statements.append(f"DROP POLICY IF EXISTS {table}_audience ON {table};")
        statements.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return "\n".join(statements)


PROFILE_TABLE = "student_learning_profiles"


def profile_rls_sql() -> str:
    """Student, linked parents and linked teachers read; only the student writes."""
    user = _user_uuid()
    using = (
        f"{tenant_policy_clause()} AND (student_user_id = {user} OR "
        f"{user} = ANY(guardian_user_ids) OR {user} = ANY(teacher_user_ids))"
    )
    check = f"{tenant_policy_clause()} AND student_user_id = {user}"
    return "\n".join(
        [
            f"ALTER TABLE {PROFILE_TABLE} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {PROFILE_TABLE} FORCE ROW LEVEL SECURITY;",
            f"DROP POLICY IF EXISTS {PROFILE_TABLE}_audience ON {PROFILE_TABLE};",
            f"CREATE POLICY {PROFILE_TABLE}_audience ON {PROFILE_TABLE} USING ({using}) WITH CHECK ({check});",
        ]
    )


def profile_rls_downgrade_sql() -> str:
    return "\n".join(
        [
            f"DROP POLICY IF EXISTS {PROFILE_TABLE}_audience ON {PROFILE_TABLE};",
            f"ALTER TABLE {PROFILE_TABLE} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {PROFILE_TABLE} DISABLE ROW LEVEL SECURITY;",
        ]
    )
