"""HTTP client to Core API for authorized learning context.

AI must NOT query Core school tables directly.
"""

from uuid import UUID

import httpx

from src.core.config import get_settings
from src.core.exceptions import UpstreamError
from src.core.telemetry import track
from src.modules.context.schemas import (
    AuthorizedLearningContext,
    CurrentLearning,
    SchoolContext,
    StudentContext,
)


class CoreClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self, bearer: str | None = None) -> dict[str, str]:
        headers = {
            "X-Internal-Token": self.settings.core_internal_token,
            "Accept": "application/json",
        }
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    async def ping(self) -> bool:
        url = f"{self.settings.core_api_url.rstrip('/')}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def get_ai_context(
        self,
        *,
        user_id: UUID,
        school_id: UUID,
        bearer_token: str | None = None,
        subject_id: UUID | None = None,
    ) -> AuthorizedLearningContext:
        """Fetch authorized learning context from Core internal API."""
        url = f"{self.settings.core_api_url.rstrip('/')}/internal/v1/students/ai-context"
        params: dict[str, str] = {"user_id": str(user_id), "school_id": str(school_id)}
        if subject_id:
            params["subject_id"] = str(subject_id)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._headers(bearer_token), params=params)

            if resp.status_code == 401:
                track("core_context_unauthorized", user_id=str(user_id))
                raise UpstreamError(
                    "Core rejected internal token — align CORE_INTERNAL_TOKEN with Core AI_SERVICE_TOKEN"
                )
            if resp.status_code == 404:
                track("core_context_missing", user_id=str(user_id))
                return self._minimal(user_id, school_id)
            if resp.status_code >= 400:
                detail = resp.text[:300]
                raise UpstreamError(f"Core AI context failed: {resp.status_code} {detail}")

            data = resp.json()
            payload = data.get("data", data) if isinstance(data, dict) else data
            return AuthorizedLearningContext.model_validate(payload)
        except UpstreamError:
            raise
        except httpx.HTTPError as exc:
            if self.settings.is_dev:
                track("core_context_fallback", error=str(exc))
                return self._minimal(user_id, school_id)
            raise UpstreamError(f"Core API unreachable: {exc}") from exc

    def _minimal(self, user_id: UUID, school_id: UUID) -> AuthorizedLearningContext:
        return AuthorizedLearningContext(
            student=StudentContext(id=user_id, class_id=None),
            school=SchoolContext(id=school_id),
            subjects=[],
            current_learning=CurrentLearning(
                topic="General study",
                taught_content=["Use class teaching records when Core is connected"],
            ),
            homework=[],
        )
