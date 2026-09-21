from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AuthDep, BearerToken, get_db
from src.modules.learning.schemas import LearningSummary
from src.modules.learning.service import LearningService

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/summary", response_model=LearningSummary)
async def learning_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: AuthDep,
    bearer: BearerToken,
):
    return await LearningService(db).summary(auth, bearer_token=bearer)
