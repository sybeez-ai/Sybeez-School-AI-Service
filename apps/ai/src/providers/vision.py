from src.providers.base import VisionProvider


class StubVision(VisionProvider):
    async def describe(self, image_url: str) -> str:
        return f"[vision stub] image at {image_url}"


def get_vision() -> VisionProvider:
    return StubVision()
