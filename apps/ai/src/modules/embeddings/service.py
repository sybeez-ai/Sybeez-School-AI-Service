from src.modules.embeddings.schemas import EmbedResponse
from src.providers.embeddings import get_embedding_provider


class EmbeddingService:
    def __init__(self) -> None:
        self.provider = get_embedding_provider()

    async def embed(self, texts: list[str]) -> EmbedResponse:
        vectors = await self.provider.embed(texts)
        dim = len(vectors[0]) if vectors else 0
        return EmbedResponse(embeddings=vectors, dim=dim)
