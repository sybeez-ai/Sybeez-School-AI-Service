"""RDS IAM database auth and Alembic URL handling.

Tokens last 15 minutes and are used only while opening a connection. The
provider refreshes them before expiry. Passwords and tokens stay out of
ConfigParser, engine URLs, and exception text.
"""

from __future__ import annotations

import logging
import os
import ssl
import threading
import time
from collections.abc import Callable

from sqlalchemy.engine.url import make_url

TOKEN_LIFETIME_SECONDS = 900
REFRESH_SKEW_SECONDS = 120

_ssl_cache: dict[str, ssl.SSLContext] = {}
_ssl_lock = threading.Lock()


def escape_alembic_url(url: str) -> str:
    """ConfigParser treats % as interpolation. A URL-encoded password must be doubled."""
    return url.replace("%", "%%")


def set_alembic_sqlalchemy_url(config, url: str) -> None:
    escaped = escape_alembic_url(url)
    try:
        config.set_main_option("sqlalchemy.url", escaped)
    except Exception:
        raise RuntimeError("Could not configure the database URL") from None


def database_endpoint(url: str) -> tuple[str, int, str, str]:
    """Return host, port, username, and database name."""
    try:
        parsed = make_url(url)
    except Exception:
        raise RuntimeError("Database URL is invalid") from None
    host = parsed.host or ""
    username = parsed.username or ""
    database = parsed.database or ""
    port = int(parsed.port or 5432)
    if not host or not username:
        raise RuntimeError("Database URL is missing a host or username")
    return host, port, username, database


# libpq options that asyncpg.connect() rejects. sslmode=require is the usual RDS form.
_LIBPQ_ONLY_QUERY = frozenset(
    {
        "ssl",
        "sslmode",
        "channel_binding",
        "sslcert",
        "sslkey",
        "sslrootcert",
        "sslcrl",
        "sslcompression",
        "ssl_min_protocol_version",
        "gssencmode",
    }
)
_SSL_ON = frozenset({"require", "verify-ca", "verify-full", "true", "1", "on"})


def _parsed_url(url: str):
    try:
        return make_url(url)
    except Exception:
        raise RuntimeError("Database URL is invalid") from None


def strip_password(url: str) -> str:
    """Return the URL with no password, so a token is not stored on the engine."""
    try:
        return _parsed_url(url)._replace(password=None).render_as_string(hide_password=False)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Database URL is invalid") from None


def url_requests_tls(url: str) -> bool:
    parsed = _parsed_url(url)
    for key in ("sslmode", "ssl"):
        value = str(parsed.query.get(key) or "").lower()
        if value in _SSL_ON:
            return True
    return False


def asyncpg_safe_url(url: str, *, drop_password: bool = False) -> str:
    """Drop libpq SSL query params. asyncpg takes an SSLContext instead."""
    parsed = _parsed_url(url)
    query = {key: value for key, value in parsed.query.items() if str(key).lower() not in _LIBPQ_ONLY_QUERY}
    if not drop_password and len(query) == len(parsed.query):
        return url
    if query != dict(parsed.query):
        parsed = parsed.set(query=query)
    if drop_password:
        parsed = parsed._replace(password=None)
    try:
        return parsed.render_as_string(hide_password=False)
    except Exception:
        raise RuntimeError("Database URL is invalid") from None


def tls_required(url: str, *, iam: bool, app_env: str, ssl_ca: str) -> bool:
    return bool(iam or app_env == "production" or ssl_ca or url_requests_tls(url))


def _session_region() -> str:
    try:
        import boto3

        return (boto3.session.Session().region_name or "").strip()
    except Exception:
        return ""


def resolve_region(aws_region: str = "") -> str:
    region = (aws_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "").strip()
    if not region:
        region = _session_region()
    if not region:
        raise RuntimeError("RDS IAM auth requires AWS_REGION")
    return region


def required_ssl_context(ca_path: str = "") -> ssl.SSLContext:
    """TLS is mandatory for RDS IAM auth. A CA bundle enables certificate checks."""
    key = ca_path or ""
    with _ssl_lock:
        cached = _ssl_cache.get(key)
        if cached is not None:
            return cached
        try:
            if key:
                context = ssl.create_default_context(cafile=key)
            else:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            raise RuntimeError("Could not configure database SSL") from None
        _ssl_cache[key] = context
        return context


class RdsIamTokenProvider:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        region: str,
        generate: Callable[[], str] | None = None,
        clock: Callable[[], float] | None = None,
        lifetime: int = TOKEN_LIFETIME_SECONDS,
        skew: int = REFRESH_SKEW_SECONDS,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.region = region
        self._generate = generate or self._boto_generate
        self._clock = clock or time.monotonic
        self.lifetime = lifetime
        self.skew = skew
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    def _boto_generate(self) -> str:
        import boto3

        client = boto3.client("rds", region_name=self.region)
        token = client.generate_db_auth_token(
            DBHostname=self.host,
            Port=self.port,
            DBUsername=self.username,
            Region=self.region,
        )
        if not token:
            raise RuntimeError("RDS IAM token generation failed")
        return token

    def token(self) -> str:
        now = self._clock()
        with self._lock:
            if self._token and now < self._expires_at - self.skew:
                return self._token
            try:
                fresh = self._generate()
            except Exception:
                raise RuntimeError("RDS IAM token generation failed") from None
            if not fresh:
                raise RuntimeError("RDS IAM token generation failed")
            self._token = fresh
            self._expires_at = now + self.lifetime
            return self._token


def raise_redacted(exc: BaseException, logger: logging.Logger, message: str) -> None:
    """Log a redacted failure and raise a new error with no chained cause."""
    from src.core.logging import redact

    logger.error("%s (%s): %s", message, type(exc).__name__, redact(exc))
    raise RuntimeError(message) from None


def iam_do_connect(provider: RdsIamTokenProvider, ssl_context: ssl.SSLContext):
    def _on_connect(dialect, conn_rec, cargs, cparams) -> None:
        cparams["password"] = provider.token()
        cparams["ssl"] = ssl_context

    return _on_connect


def iam_engine_options(url: str, *, aws_region: str, ssl_ca: str) -> tuple[str, dict, Callable]:
    """URL without a password, asyncpg connect args, and a do_connect listener."""
    safe_url, connect_args, listener = database_connect(
        url,
        iam=True,
        app_env="",
        aws_region=aws_region,
        ssl_ca=ssl_ca,
    )
    return safe_url, connect_args, listener


def database_connect(
    url: str,
    *,
    iam: bool,
    app_env: str,
    aws_region: str,
    ssl_ca: str,
) -> tuple[str, dict, Callable | None]:
    """Return an asyncpg URL, connect args, and an optional IAM token listener."""
    safe_url = asyncpg_safe_url(url, drop_password=iam)
    connect_args: dict = {}
    listener = None
    if tls_required(url, iam=iam, app_env=app_env, ssl_ca=ssl_ca):
        ssl_context = required_ssl_context(ssl_ca)
        connect_args["ssl"] = ssl_context
        if iam:
            host, port, username, _database = database_endpoint(url)
            provider = RdsIamTokenProvider(
                host=host,
                port=port,
                username=username,
                region=resolve_region(aws_region),
            )
            listener = iam_do_connect(provider, ssl_context)
    return safe_url, connect_args, listener
