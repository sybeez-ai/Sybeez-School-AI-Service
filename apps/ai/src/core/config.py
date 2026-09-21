from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = "postgresql+asyncpg://sybeez:sybeez@localhost:5432/sybeez_school"
    database_url_sync: str = "postgresql://sybeez:sybeez@localhost:5432/sybeez_school"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"

    core_api_url: str = "http://localhost:8000"
    # Must match Core AI_SERVICE_TOKEN / CORE_INTERNAL_TOKEN
    core_internal_token: str = "dev-internal-service-token"

    # deepseek | qwen | sarvam | openai
    llm_provider: str = "deepseek"
    chat_stream_enabled: bool = True
    embedding_dim: int = 1536

    # Sarvam
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"

    # Qwen
    qwen_voice_api_key: str = ""
    qwen_chat_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.alibaba.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen-plus"
    qwen_voice_model: str = "qwen-audio-turbo"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"

    # OpenAI fallback
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ai_cors_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

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
        return (
            self.deepseek_api_key
            or self.qwen_chat_api_key
            or self.openai_api_key
            or self.sarvam_api_key
        )

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
