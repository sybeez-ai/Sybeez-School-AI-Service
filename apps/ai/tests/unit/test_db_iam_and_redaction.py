import logging
import ssl
import sys

import pytest
from alembic.config import Config
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.engine.url import make_url

from src.core.config import Settings
from src.core.database import assert_database_role_enforces_rls, build_async_engine
from src.core.db_iam import (
    RdsIamTokenProvider,
    asyncpg_safe_url,
    database_connect,
    database_endpoint,
    iam_do_connect,
    raise_redacted,
    required_ssl_context,
    resolve_region,
    set_alembic_sqlalchemy_url,
    strip_password,
)
from src.core.exceptions import AppError
from src.core.logging import install_redaction, redact, setup_logging
from src.main import app
from tests.security.jwks import bearer, mint

SECRET_URL = "postgresql+asyncpg://sybeez_app:s3cret@db.internal:5432/sybeez"
client = TestClient(app)


def test_alembic_url_round_trips_percent_encoded_password():
    url = "postgresql+asyncpg://sybeez_app:p%40ss@db.internal:5432/sybeez"
    cfg = Config()
    set_alembic_sqlalchemy_url(cfg, url)
    assert cfg.get_main_option("sqlalchemy.url") == url


def test_alembic_url_failure_hides_the_url():
    class Boom:
        def set_main_option(self, name, value):
            raise ValueError(f"invalid interpolation syntax in {value!r}")

    with pytest.raises(RuntimeError) as exc:
        set_alembic_sqlalchemy_url(Boom(), SECRET_URL)
    assert "s3cret" not in str(exc.value)
    assert "db.internal" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_strip_password_and_endpoint():
    assert strip_password(SECRET_URL) == "postgresql+asyncpg://sybeez_app@db.internal:5432/sybeez"
    host, port, username, database = database_endpoint(SECRET_URL)
    assert (host, port, username, database) == ("db.internal", 5432, "sybeez_app", "sybeez")
    with pytest.raises(RuntimeError) as exc:
        database_endpoint("not-a-database-url")
    assert "not-a-database-url" not in str(exc.value)
    assert exc.value.__cause__ is None
    with pytest.raises(RuntimeError) as missing:
        database_endpoint("postgresql://localhost/sybeez")
    assert "localhost" not in str(missing.value)


def test_token_is_cached_until_the_refresh_window():
    now = {"t": 1_000.0}
    calls = {"n": 0}

    def generate() -> str:
        calls["n"] += 1
        return f"token-{calls['n']}"

    provider = RdsIamTokenProvider(
        host="db.internal",
        port=5432,
        username="sybeez_app",
        region="ap-south-1",
        generate=generate,
        clock=lambda: now["t"],
        lifetime=900,
        skew=120,
    )
    assert provider.token() == "token-1"
    now["t"] = 1_779
    assert provider.token() == "token-1"
    now["t"] = 1_780
    assert provider.token() == "token-2"
    assert calls["n"] == 2


def test_token_generation_failure_hides_host():
    def generate() -> str:
        raise RuntimeError("could not sign db.internal")

    provider = RdsIamTokenProvider(
        host="db.internal",
        port=5432,
        username="sybeez_app",
        region="ap-south-1",
        generate=generate,
        clock=lambda: 0.0,
    )
    with pytest.raises(RuntimeError) as exc:
        provider.token()
    assert "db.internal" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_empty_token_is_rejected():
    provider = RdsIamTokenProvider(
        host="db.internal",
        port=5432,
        username="sybeez_app",
        region="ap-south-1",
        generate=lambda: "",
        clock=lambda: 0.0,
    )
    with pytest.raises(RuntimeError) as exc:
        provider.token()
    assert "db.internal" not in str(exc.value)


def test_boto_generate_db_auth_token(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def generate_db_auth_token(self, **kwargs):
            captured.update(kwargs)
            return "signed-token"

    class FakeBoto:
        def client(self, name, region_name=None):
            captured["service"] = name
            captured["region_name"] = region_name
            return FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto())
    provider = RdsIamTokenProvider(
        host="db.example.com",
        port=5432,
        username="sybeez_app",
        region="ap-south-1",
    )
    assert provider.token() == "signed-token"
    assert captured["service"] == "rds"
    assert captured["region_name"] == "ap-south-1"
    assert captured["DBHostname"] == "db.example.com"
    assert captured["Port"] == 5432
    assert captured["DBUsername"] == "sybeez_app"
    assert captured["Region"] == "ap-south-1"


def test_listener_sets_password_and_ssl():
    provider = RdsIamTokenProvider(
        host="db.internal",
        port=5432,
        username="sybeez_app",
        region="ap-south-1",
        generate=lambda: "iam-token",
        clock=lambda: 0.0,
    )
    context = required_ssl_context("")
    cparams = {"password": "stored-password"}
    iam_do_connect(provider, context)(None, None, [], cparams)
    assert cparams["password"] == "iam-token"
    assert cparams["ssl"] is context
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False
    assert required_ssl_context("") is context


def test_ssl_ca_failure_hides_path():
    with pytest.raises(RuntimeError) as exc:
        required_ssl_context("/tmp/missing-rds-ca.pem")
    assert "missing-rds-ca" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_region_is_required(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr("src.core.db_iam._session_region", lambda: "")
    with pytest.raises(RuntimeError) as exc:
        resolve_region("")
    assert "AWS_REGION" in str(exc.value)


def test_sslmode_becomes_an_asyncpg_tls_context():
    raw = "postgresql+asyncpg://sybeez_app:p%40ss@db.internal:5432/sybeez?sslmode=require"
    safe = asyncpg_safe_url(raw)
    assert "sslmode" not in safe
    assert make_url(safe).password == "p@ss"
    safe, connect_args, listener = database_connect(
        raw,
        iam=False,
        app_env="production",
        aws_region="",
        ssl_ca="",
    )
    assert "sslmode" not in safe
    assert make_url(safe).password == "p@ss"
    assert isinstance(connect_args["ssl"], ssl.SSLContext)
    assert listener is None
    unchanged, empty, no_listener = database_connect(
        "postgresql+asyncpg://sybeez:sybeez@localhost:5432/sybeez_school",
        iam=False,
        app_env="test",
        aws_region="",
        ssl_ca="",
    )
    assert unchanged == "postgresql+asyncpg://sybeez:sybeez@localhost:5432/sybeez_school"
    assert empty == {}
    assert no_listener is None


def test_engine_without_iam_keeps_the_password():
    built = build_async_engine(
        Settings(
            database_url="postgresql+asyncpg://sybeez:sybeez@localhost:5432/sybeez_school",
            db_iam_auth=False,
        )
    )
    try:
        assert built.url.password == "sybeez"
        assert built.pool._recycle == 1800
        try:
            listeners = list(built.sync_engine.dispatch.do_connect)
        except AttributeError:
            listeners = []
        assert listeners == []
    finally:
        built.sync_engine.dispose()


def test_engine_with_iam_strips_password_and_injects_token(monkeypatch):
    class FakeProvider(RdsIamTokenProvider):
        def __init__(self, **kwargs):
            kwargs["generate"] = lambda: "iam-token"
            kwargs["clock"] = lambda: 0.0
            super().__init__(**kwargs)

    monkeypatch.setattr("src.core.db_iam.RdsIamTokenProvider", FakeProvider)
    built = build_async_engine(
        Settings(
            database_url=SECRET_URL,
            db_iam_auth=True,
            aws_region="ap-south-1",
        )
    )
    try:
        assert built.url.password is None
        assert "s3cret" not in built.url.render_as_string(hide_password=False)
        assert built.pool._recycle == 600
        cparams = {"password": "stored-password"}
        built.sync_engine.dialect.dispatch.do_connect(built.sync_engine.dialect, None, [], cparams)
        assert cparams["password"] == "iam-token"
        assert isinstance(cparams["ssl"], ssl.SSLContext)
    finally:
        built.sync_engine.dispose()


def test_redact_urls_passwords_and_iam_tokens():
    raw = (
        "connect postgresql+asyncpg://sybeez_app:s3cret@db.internal:5432/sybeez "
        "password=hunter2 X-Amz-Signature=abcd1234 X-Amz-Credential=AKIAEXAMPLE"
    )
    cleaned = redact(raw)
    assert "s3cret" not in cleaned
    assert "db.internal" not in cleaned
    assert "hunter2" not in cleaned
    assert "abcd1234" not in cleaned
    assert "AKIAEXAMPLE" not in cleaned
    assert cleaned == redact(cleaned)


def test_formatter_and_logs_redact_exceptions(capsys):
    install_redaction()
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        setup_logging("INFO")
        try:
            raise RuntimeError(SECRET_URL)
        except RuntimeError:
            text = logging.Formatter().formatException(sys.exc_info())
            logging.getLogger("test.redact").exception("connect failed")
        assert "s3cret" not in text
        assert "db.internal" not in text
        captured = capsys.readouterr().out
        assert "s3cret" not in captured
        assert "db.internal" not in captured
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)


def test_failure_reason_redacts_the_database_url():
    from src.migrate import failure_reason

    reason = failure_reason(
        "ERROR [alembic.env] Database migration failed (InvalidPasswordError): "
        "postgresql+asyncpg://sybeez_app:s3cret@db.internal/sybeez\n"
        "RuntimeError: Database migration failed\n"
    )
    assert "s3cret" not in reason
    assert "db.internal" not in reason
    assert "Database migration failed" in reason
    assert len(reason) <= 255


def test_raise_redacted_drops_the_cause(caplog):
    caplog.set_level(logging.ERROR)
    with pytest.raises(RuntimeError) as exc:
        try:
            raise ValueError(SECRET_URL)
        except ValueError as original:
            raise_redacted(original, logging.getLogger("alembic.env"), "Database migration failed")
    assert "s3cret" not in str(exc.value)
    assert "db.internal" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert "s3cret" not in caplog.text
    assert "db.internal" not in caplog.text
    assert "[redacted-url]" in caplog.text


async def test_role_check_does_not_chain_the_url(monkeypatch):
    class Broken:
        def connect(self):
            return self

        async def __aenter__(self):
            raise RuntimeError(SECRET_URL)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.core.database.engine", Broken())
    with pytest.raises(RuntimeError) as exc:
        await assert_database_role_enforces_rls()
    assert "s3cret" not in str(exc.value)
    assert "db.internal" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_http_errors_redact_database_urls(monkeypatch):
    async def app_error(self, auth, body, bearer_token=None):
        raise AppError(f"connect {SECRET_URL} failed")

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", app_error)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert response.status_code == 400
    assert "s3cret" not in response.text
    assert "db.internal" not in response.text

    async def http_error(self, auth, body, bearer_token=None):
        raise HTTPException(status_code=400, detail=SECRET_URL)

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", http_error)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert "s3cret" not in response.text
    assert "db.internal" not in response.text

    async def invalid(self, auth, body, bearer_token=None):
        raise RequestValidationError(
            [{"loc": ["body"], "msg": f"bad {SECRET_URL}", "type": "value_error"}]
        )

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", invalid)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert response.status_code == 422
    assert "s3cret" not in response.text
    assert "db.internal" not in response.text

    async def boom(self, auth, body, bearer_token=None):
        raise RuntimeError(SECRET_URL)

    monkeypatch.setattr("src.modules.practice.router.PracticeService.generate", boom)
    response = client.post("/api/v1/ai/practice", headers=bearer(mint()), json={"count": 1})
    assert response.status_code == 500
    assert "s3cret" not in response.text
    assert "db.internal" not in response.text
