import json
import re
from uuid import uuid4

from src.core.security import AuthContext
from src.modules.context.service import ContextService
from src.modules.practice.schemas import PracticeQuestion, PracticeRequest, PracticeResponse
from src.providers.llm import get_llm
from src.shared.utils import load_prompt


class PracticeService:
    def __init__(self) -> None:
        self.context = ContextService()
        self.llm = get_llm()

    async def generate(
        self, auth: AuthContext, body: PracticeRequest, *, bearer_token: str | None = None
    ) -> PracticeResponse:
        learning = await self.context.for_user(auth, bearer_token=bearer_token, subject_id=body.subject_id)
        topic = body.topic or (learning.current_learning.topic if learning.current_learning else "General")
        system = load_prompt("system/ai_teacher.txt")
        instruction = load_prompt("practice/generate.txt")
        user = (
            f"{instruction}\n\n"
            f"Context:\n{learning.as_prompt_block()}\n\n"
            f"Topic: {topic}\nDifficulty: {body.difficulty.value}\nCount: {body.count}\n\n"
            "Return JSON array of objects with keys: prompt, question_type, hint."
        )
        raw = await self.llm.complete(system=system, user=user)
        questions = self._parse(raw, body.count)
        return PracticeResponse(topic=topic or "General", difficulty=body.difficulty.value, questions=questions)

    def _parse(self, raw: str, count: int) -> list[PracticeQuestion]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                out = []
                for item in data[:count]:
                    out.append(
                        PracticeQuestion(
                            id=str(uuid4()),
                            prompt=item.get("prompt", "Practice question"),
                            question_type=item.get("question_type", "short_answer"),
                            hint=item.get("hint"),
                        )
                    )
                if out:
                    return out
            except json.JSONDecodeError:
                pass
        # Fallback questions from echo LLM
        return [
            PracticeQuestion(
                id=str(uuid4()),
                prompt=f"Practice {i + 1}: Explain one key idea from today's topic in your own words.",
                hint="Use terms your teacher used in class.",
            )
            for i in range(count)
        ]
