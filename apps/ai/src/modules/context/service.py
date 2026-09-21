from uuid import UUID

from src.core.security import AuthContext, require_school
from src.modules.context.core_client import CoreClient
from src.modules.context.schemas import AuthorizedLearningContext


class ContextService:
    def __init__(self) -> None:
        self.core = CoreClient()

    async def for_user(
        self,
        auth: AuthContext,
        *,
        bearer_token: str | None = None,
        subject_id: UUID | None = None,
    ) -> AuthorizedLearningContext:
        school_id = require_school(auth)
        return await self.core.get_ai_context(
            user_id=auth.user_id,
            school_id=school_id,
            bearer_token=bearer_token,
            subject_id=subject_id,
        )
