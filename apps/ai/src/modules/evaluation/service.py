import json
import re

from src.core.security import AuthContext
from src.modules.context.service import ContextService
from src.modules.evaluation.schemas import EvaluationRequest, EvaluationResponse
from src.providers.llm import get_llm, guarded_complete
from src.shared.utils import load_prompt


class EvaluationService:
    def __init__(self) -> None:
        self.context = ContextService()
        self.llm = get_llm()

    async def evaluate(
        self, auth: AuthContext, body: EvaluationRequest, *, bearer_token: str | None = None
    ) -> EvaluationResponse:
        learning = await self.context.for_user(auth, bearer_token=bearer_token)
        system = load_prompt("system/ai_teacher.txt")
        instruction = load_prompt("evaluation/evaluate.txt")
        user = (
            f"{instruction}\n\n"
            f"Context:\n{learning.as_prompt_block()}\n\n"
            f"Topic: {body.topic or 'n/a'}\n"
            f"Question: {body.question}\n"
            f"Expected: {body.expected or 'n/a'}\n"
            f"Student answer: {body.answer}\n\n"
            'Return JSON: {"correct": bool, "score": 0-1, "feedback": str, '
            '"concepts_demonstrated": [], "concepts_missing": []}'
        )
        raw = await guarded_complete(self.llm, system=system, user=user)
        parsed = self._parse(raw, body.answer)
        return parsed

    def _parse(self, raw: str, answer: str) -> EvaluationResponse:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return EvaluationResponse(
                    correct=bool(data.get("correct", False)),
                    score=float(data.get("score", 0)),
                    feedback=str(data.get("feedback", "")),
                    concepts_demonstrated=list(data.get("concepts_demonstrated") or []),
                    concepts_missing=list(data.get("concepts_missing") or []),
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        # Heuristic fallback for echo mode
        looks_ok = len(answer.strip()) > 20
        return EvaluationResponse(
            correct=looks_ok,
            score=1.0 if looks_ok else 0.3,
            feedback="Good effort. Compare your answer with the law or definition taught in class."
            if looks_ok
            else "Try again using the key terms from the lesson.",
            concepts_demonstrated=["attempt"] if looks_ok else [],
            concepts_missing=[] if looks_ok else ["core_definition"],
        )
