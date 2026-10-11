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
