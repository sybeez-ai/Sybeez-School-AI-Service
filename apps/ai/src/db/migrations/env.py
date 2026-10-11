import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import event, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.core.config import get_settings
from src.core.db_iam import iam_engine_options, raise_redacted, set_alembic_sqlalchemy_url, strip_password
from src.core.logging import install_redaction
from src.db import models  # noqa: F401
from src.db.base import Base

install_redaction()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
install_redaction()

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata
settings = get_settings()


def _alembic_url() -> str:
    if settings.db_iam_auth:
        return strip_password(settings.database_url)
    return settings.database_url


set_alembic_sqlalchemy_url(config, _alembic_url())


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _migration_failure(exc: BaseException) -> None:
    raise_redacted(exc, logger, "Database migration failed")


async def run_async_migrations() -> None:
    connect_args: dict = {}
    listener = None
    if settings.db_iam_auth:
        _url, iam_args, listener = iam_engine_options(
            settings.database_url,
            aws_region=settings.aws_region,
            ssl_ca=settings.db_ssl_ca,
        )
        connect_args.update(iam_args)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    if listener is not None:
        event.listen(connectable.sync_engine, "do_connect", listener)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


try:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
except Exception as exc:
    _migration_failure(exc)
