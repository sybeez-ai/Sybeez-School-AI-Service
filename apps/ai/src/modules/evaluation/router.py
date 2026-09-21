from typing import Annotated

from fastapi import APIRouter

from src.api.dependencies import AuthDep, BearerToken
from src.modules.evaluation.schemas import EvaluationRequest, EvaluationResponse
from src.modules.evaluation.service import EvaluationService

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("", response_model=EvaluationResponse)
async def evaluate(body: EvaluationRequest, auth: AuthDep, bearer: BearerToken):
    return await EvaluationService().evaluate(auth, body, bearer_token=bearer)
