import logging
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import Settings, get_settings
from src.core.db_iam import database_connect

logger = logging.getLogger("sybeez.ai.database")

settings = get_settings()


def build_async_engine(settings: Settings):
    connect_args = {
        "timeout": settings.db_connect_timeout_seconds,
        "command_timeout": settings.db_statement_timeout_ms / 1000 + 5,
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(settings.db_idle_tx_timeout_ms),
            "application_name": "sybeez-ai",
        },
    }
    recycle = 1800
    url, security_args, listener = database_connect(
        settings.database_url,
        iam=settings.db_iam_auth,
        app_env=settings.app_env,
        aws_region=settings.aws_region,
        ssl_ca=settings.db_ssl_ca,
    )
    connect_args.update(security_args)
    if settings.db_iam_auth:
        recycle = 600
    engine = create_async_engine(
        url,
        echo=settings.sql_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=recycle,
        connect_args=connect_args,
    )
    if listener is not None:
        event.listen(engine.sync_engine, "do_connect", listener)
    return engine


engine = build_async_engine(settings)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# set_config(..., true) is SET LOCAL. SET LOCAL cannot take a bound parameter.
TENANT_SCHOOL_SQL = "SELECT set_config('app.school_id', :school_id, true)"
TENANT_USER_SQL = "SELECT set_config('app.user_id', :user_id, true)"
TENANT_ROLE_SQL = "SELECT set_config('app.role', :role, true)"


def tenant_context_statements(
    school_id: UUID, user_id: UUID, role: str | None = None
) -> list[tuple[str, dict[str, str]]]:
    statements: list[tuple[str, dict[str, str]]] = [
        (TENANT_SCHOOL_SQL, {"school_id": str(school_id)}),
        (TENANT_USER_SQL, {"user_id": str(user_id)}),
    ]
    if role:
        # The backend's restrictive *_role policies read app.role; without it they fail closed.
        statements.append((TENANT_ROLE_SQL, {"role": role}))
    return statements


def install_tenant_context(
    session: AsyncSession, *, school_id: UUID, user_id: UUID, role: str | None = None
) -> None:
    """Apply token identity to every transaction on this session.

    The third argument of set_config is is_local=true, so the values die with the
    transaction and cannot leak to the next pooled connection.
    """
    statements = tenant_context_statements(school_id, user_id, role)

    def _apply(_session, _transaction, connection) -> None:
        for sql, params in statements:
            connection.execute(text(sql), params)

    event.listen(session.sync_session, "after_begin", _apply)
    session.info["school_id"] = str(school_id)
    session.info["user_id"] = str(user_id)


async def assert_database_role_enforces_rls() -> None:
    """Superusers and BYPASSRLS roles ignore policies, including FORCE RLS."""
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
            bypasses = result.scalar_one()
    except Exception as exc:
        logger.error("database role check failed: %s", type(exc).__name__)
        raise RuntimeError("Database is not reachable; refusing to start") from None
    if bypasses:
        raise RuntimeError("Database role is superuser or BYPASSRLS; RLS would not isolate tenants")
