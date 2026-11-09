"""HTTP client to Core API for authorized learning context.

AI must NOT query Core school tables directly.
"""

import hashlib
import time
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

# Successful parent-child lookups are reused briefly so opening a lesson does not
# ask Core twice. Failures are not cached: a blip must not hide history for long.
_PARENT_CHILD_TTL = 15.0
_parent_child_cache: dict[str, tuple[float, set[UUID]]] = {}

# Live guardian links. Not the exams list: that route is refused when a school
# switches exams off, which would hide every parent's lesson history.
_PARENTS_CHILDREN_PATH = "/api/v1/parents/me/children"
_EXAMS_CHILDREN_PATH = "/api/v1/exams/parent/children"


def reset_parent_child_cache() -> None:
    _parent_child_cache.clear()


def parse_child_ids(payload: object) -> set[UUID]:
    """Student record ids from a Core children list, or from `{data: [...]}` / `{children: [...]}`."""
    rows: object = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("children"))
    found: set[UUID] = set()
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            found.add(UUID(str(row.get("student_id"))))
        except (TypeError, ValueError):
            continue
    return found


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
            async with httpx.AsyncClient(timeout=self.settings.health_timeout_seconds) as client:
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
            async with httpx.AsyncClient(timeout=self.settings.upstream_timeout_seconds) as client:
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
                track("core_context_failed", status=resp.status_code)
                raise UpstreamError("Core AI context failed")

            data = resp.json()
            payload = data.get("data", data) if isinstance(data, dict) else data
            return AuthorizedLearningContext.model_validate(payload)
        except UpstreamError:
            raise
        except httpx.HTTPError as exc:
            track("core_context_unreachable", error_type=type(exc).__name__)
            if self.settings.is_dev:
                return self._minimal(user_id, school_id)
            raise UpstreamError("Core API unreachable") from exc

    async def parent_child_ids(self, *, bearer_token: str | None) -> set[UUID]:
        """Student record ids the calling parent is linked to in Core right now.

        Uses `/api/v1/parents/me/children`, which stays available when exams are
        switched off. The exams children route is used only if that path is missing
        (HTTP 404) on an older Core. Any other error fails closed: an unverifiable
        link never grants lesson or profile access. A parent portal that is itself
        switched off (403) does not fall through to exams.
        """
        if not bearer_token:
            return set()
        key = hashlib.sha256(bearer_token.encode()).hexdigest()
        now = time.monotonic()
        hit = _parent_child_cache.get(key)
        if hit and now - hit[0] < _PARENT_CHILD_TTL:
            return set(hit[1])
        found = await self._load_parent_children(bearer_token)
        if found is None:
            return set()
        if len(_parent_child_cache) > 2000:
            _parent_child_cache.clear()
        _parent_child_cache[key] = (now, set(found))
        return set(found)

    async def _load_parent_children(self, bearer_token: str) -> set[UUID] | None:
        status, payload = await self._get_json(_PARENTS_CHILDREN_PATH, bearer_token)
        if status == 404:
            track("core_parent_children_parents_route_missing")
            status, payload = await self._get_json(_EXAMS_CHILDREN_PATH, bearer_token)
        if status is None or status >= 400 or payload is None:
            if status is not None and status >= 400:
                track("core_parent_children_failed", status=status)
            return None
        return parse_child_ids(payload)

    async def _get_json(self, path: str, bearer_token: str) -> tuple[int | None, object]:
        url = f"{self.settings.core_api_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.upstream_timeout_seconds) as client:
                resp = await client.get(url, headers=self._headers(bearer_token))
            if resp.status_code >= 400:
                return resp.status_code, None
            return resp.status_code, resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            track("core_parent_children_unreachable", error_type=type(exc).__name__)
            return None, None

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
