from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int
