"""School-scoped row level security for AI-owned tables.

Policies compare school_id to the transaction-local GUC app.school_id, which the
API sets from the verified token. app.user_id is set in the same transaction for
audit and future per-user policies. Tenant isolation does not use user_id in the
policy because knowledge rows are shared inside a school; conversation queries
still filter user_id in the application.
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
