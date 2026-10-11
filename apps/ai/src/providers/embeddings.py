import httpx

from src.core.config import get_settings
from src.providers.base import EmbeddingProvider


class ZeroEmbeddingProvider(EmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        dim = get_settings().embedding_dim
        return [[0.0] * dim for _ in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        settings = get_settings()
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=settings.upstream_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.openai_base_url}/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.embedding_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.has_openai:
        return OpenAIEmbeddingProvider()
    return ZeroEmbeddingProvider()
