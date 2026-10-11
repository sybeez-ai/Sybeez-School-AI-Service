"""LLM provider configuration and failure mapping."""

from urllib.parse import urlparse

import httpx
import pytest

from src.core.config import Settings
from src.core.exceptions import UpstreamError
from src.providers import llm as llm_module


def test_qwen_default_base_url_is_the_real_dashscope_host():
    # dashscope-intl.alibaba.com does not resolve; production 500'd every AI Teacher lesson.
    host = urlparse(Settings().qwen_base_url).hostname
    assert host == "dashscope-intl.aliyuncs.com"


@pytest.mark.asyncio
async def test_unreachable_provider_raises_upstream_error(monkeypatch):
    provider = llm_module.CompatibleChatLLM.__new__(llm_module.CompatibleChatLLM)
    provider.settings = Settings()
    provider.api_key = "test"
    provider.base_url = "https://unreachable.invalid"
    provider.model = "m"

    async def boom(*_args, **_kwargs):
        raise httpx.ConnectError("Name or service not known")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    with pytest.raises(UpstreamError):
        await provider.complete(system="s", user="u")


def _clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "AI_FALLBACK_PROVIDER", "QWEN_API_KEY", "QWEN_CHAT_API_KEY",
                 "QWEN_VOICE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_qwen_api_key_secret_name_is_accepted(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "q-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d-key")
    s = Settings(_env_file=None)
    assert s.chat_provider == "qwen"
    assert s.active_chat_api_key == "q-key"
    assert "aliyuncs.com" in s.active_chat_base_url
    assert s.active_chat_model == s.qwen_chat_model
    assert s.qwen_voice_api_key == "q-key"


def test_missing_preferred_key_uses_fallback_provider_consistently(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d-key")
    s = Settings(_env_file=None)
    assert s.chat_provider == "deepseek"
    assert s.active_chat_api_key == "d-key"
    assert s.active_chat_base_url == s.deepseek_base_url
    assert s.active_chat_model == s.deepseek_chat_model
