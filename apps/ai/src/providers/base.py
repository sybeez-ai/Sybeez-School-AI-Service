from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, *, system: str, user: str) -> str: ...

    @abstractmethod
    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]: ...


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VisionProvider(ABC):
    @abstractmethod
    async def describe(self, image_url: str) -> str: ...
