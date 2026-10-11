
from fastapi import APIRouter

from src.api.dependencies import AuthDep, BearerToken
from src.modules.practice.schemas import PracticeRequest, PracticeResponse
from src.modules.practice.service import PracticeService

router = APIRouter(prefix="/practice", tags=["practice"])


@router.post("", response_model=PracticeResponse)
async def generate_practice(body: PracticeRequest, auth: AuthDep, bearer: BearerToken):
    return await PracticeService().generate(auth, body, bearer_token=bearer)
