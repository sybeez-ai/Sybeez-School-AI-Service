"""Student doubt about the page their teacher uploaded for their class today."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep, BearerToken
from src.core.security import require_school
from src.modules.classroom.material import ClassroomMaterial
from src.modules.classroom.orchestrator import ClassroomOrchestrator
from src.providers.llm import get_llm

router = APIRouter(prefix="/classroom", tags=["classroom"])


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    class_section_id: UUID
    on: str = Field(default_factory=lambda: date.today().isoformat(), pattern=r"^\d{4}-\d{2}-\d{2}$")
    session_id: UUID | None = None
    session_memory: list[str] = Field(default_factory=list, max_length=8)


@router.post("/turn")
async def classroom_turn(body: TurnRequest, auth: AuthDep, bearer: BearerToken):
    require_school(auth)
    body.session_memory = [item.strip()[:200] for item in body.session_memory if item.strip()][:8]
    orchestrator = ClassroomOrchestrator(ClassroomMaterial(), get_llm())
    return await orchestrator.turn(auth, body, bearer)
