import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.secrets import apply_secret_mapping, fetch_secrets_manager_json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    ai_host: str = "0.0.0.0"
    ai_port: int = 8001
    ai_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    root_path: str = ""
    log_level: str = "INFO"
    sql_echo: bool = False

    database_url: str = "postgresql+asyncpg://sybeez:sybeez@localhost:5432/sybeez_school"
    database_url_sync: str = "postgresql://sybeez:sybeez@localhost:5432/sybeez_school"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 5
    db_connect_timeout_seconds: float = 5
    db_statement_timeout_ms: int = 15000
    db_idle_tx_timeout_ms: int = 15000

    redis_url: str = "redis://localhost:6379/0"
    rate_limit_backend: str = "memory"
    rate_limit_per_minute: int = 60
    rate_limit_window_seconds: int = 60
    trust_proxy: bool | None = None

    request_timeout_seconds: float = 30
    stream_timeout_seconds: float = 120
    upstream_timeout_seconds: float = 15
    health_timeout_seconds: float = 3
    jwks_timeout_seconds: float = 3
    llm_timeout_seconds: float = 60
    max_body_bytes: int = 1_048_576

    # Cognito access and ID tokens. Claims mirror the backend: sub/user_id, role, school_id.
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_jwks_cache_seconds: int = 3600

    # School backend session tokens: HS256 signed with the shared JWT_SECRET.
    # create_access_token does not set iss or aud. Leave these empty to match.
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = ""
    jwt_audience: str = ""

    aws_region: str = ""
    aws_secrets_manager_secret_id: str = ""

    core_api_url: str = "http://localhost:8000"
    core_internal_token: str = "dev-internal-service-token"

    llm_provider: str = "deepseek"
    chat_stream_enabled: bool = True
    embedding_dim: int = 1536

    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"

    qwen_voice_api_key: str = ""
    qwen_chat_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.alibaba.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen-plus"
    qwen_voice_model: str = "qwen-audio-turbo"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ai_cors_origins.split(",") if origin.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def cognito_configured(self) -> bool:
        return bool(self.cognito_region and self.cognito_user_pool_id and self.cognito_app_client_id)

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"

    def client_trusts_proxy(self) -> bool:
        if self.trust_proxy is None:
            return self.app_env == "production"
        return self.trust_proxy

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_deepseek(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def has_qwen_chat(self) -> bool:
        return bool(self.qwen_chat_api_key)

    @property
    def has_qwen_voice(self) -> bool:
        return bool(self.qwen_voice_api_key)

    @property
    def has_sarvam(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def active_chat_api_key(self) -> str:
        provider = self.llm_provider.lower()
        if provider == "deepseek" and self.deepseek_api_key:
            return self.deepseek_api_key
        if provider == "qwen" and self.qwen_chat_api_key:
            return self.qwen_chat_api_key
        if provider == "openai" and self.openai_api_key:
            return self.openai_api_key
        return self.deepseek_api_key or self.qwen_chat_api_key or self.openai_api_key or self.sarvam_api_key

    @property
    def active_chat_base_url(self) -> str:
        provider = self.llm_provider.lower()
        if provider == "deepseek":
            return self.deepseek_base_url
        if provider == "qwen":
            return self.qwen_base_url
        if provider == "openai":
            return self.openai_base_url
        if self.deepseek_api_key:
            return self.deepseek_base_url
        if self.qwen_chat_api_key:
            return self.qwen_base_url
        return self.openai_base_url

    @property
    def active_chat_model(self) -> str:
        provider = self.llm_provider.lower()
        if provider == "deepseek":
            return self.deepseek_chat_model
        if provider == "qwen":
            return self.qwen_chat_model
        return self.llm_model


_INSECURE_SECRETS = frozenset(
    {
        "",
        "change-me-in-production",
        "change-me-in-production-use-long-random-string",
        "dev-only-change-me",
    }
)


def secret_is_insecure(value: str) -> bool:
    cleaned = (value or "").strip()
    if cleaned in _INSECURE_SECRETS:
        return True
    return len(cleaned) < 32


def validate_production_settings(settings: Settings) -> None:
    """Fail closed before serving when production is pointed at dev defaults."""
    if settings.app_env != "production":
        return
    problems: list[str] = []
    if not settings.cognito_region:
        problems.append("COGNITO_REGION")
    if not settings.cognito_user_pool_id:
        problems.append("COGNITO_USER_POOL_ID")
    if not settings.cognito_app_client_id:
        problems.append("COGNITO_APP_CLIENT_ID")
    if settings.jwt_algorithm != "HS256" or secret_is_insecure(settings.jwt_secret):
        problems.append("JWT_SECRET")
    if "sybeez:sybeez@" in settings.database_url or not settings.database_url.strip():
        problems.append("DATABASE_URL")
    if settings.core_internal_token == "dev-internal-service-token":
        problems.append("CORE_INTERNAL_TOKEN")
    if problems:
        raise RuntimeError("Refusing to start in production. Fix: " + ", ".join(problems))


def _load_settings() -> Settings:
    settings = Settings()
    secret_id = settings.aws_secrets_manager_secret_id.strip()
    if not secret_id:
        return settings
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or settings.aws_region
        or settings.cognito_region
        or None
    )
    payload = fetch_secrets_manager_json(secret_id, region)
    apply_secret_mapping(payload)
    return Settings()


@lru_cache
def get_settings() -> Settings:
    return _load_settings()
