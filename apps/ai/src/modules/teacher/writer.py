"""Ask the model for board JSON and validate it, with retries."""

import json
import logging
import re

from pydantic import ValidationError

from src.core.config import get_settings
from src.modules.teacher.protocol import LessonPlan, ProtocolError, StepScript, prepare_actions
from src.shared.utils import load_prompt

logger = logging.getLogger("sybeez.ai.teacher.writer")


def extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("json must be an object")
    return data


class LessonWriter:
    def __init__(self, llm, retries: int | None = None):
        self.llm = llm
        self.retries = retries if retries is not None else get_settings().teacher_schema_retries

    def system(self) -> str:
        base = load_prompt("system/ai_teacher.txt")
        board = load_prompt("teaching/board.txt")
        return f"{base}\n\n{board}".strip()

    async def write_model(self, model, *, user: str):
        prompt = user
        last = "invalid"
        for _ in range(max(1, self.retries)):
            raw = await self.llm.complete(system=self.system(), user=prompt)
            try:
                parsed = model.model_validate(extract_json(raw))
                if isinstance(parsed, StepScript):
                    parsed.actions = prepare_actions(list(parsed.actions))
                    if not any(action.type == "narration" for action in parsed.actions):
                        raise ValueError("actions must include narration")
                return parsed
            except (ValueError, ValidationError, ProtocolError, json.JSONDecodeError) as exc:
                last = str(exc)
                prompt = (
                    f"{user}\n\nThe previous response failed the board schema.\n"
                    f"Validation error: {last[:1200]}\n"
                    "Return one JSON object only. Do not include markdown or hidden reasoning in chat."
                )
        logger.info("board schema retries exhausted")
        raise ProtocolError(last)

    async def write_plan(self, *, user: str) -> LessonPlan:
        return await self.write_model(LessonPlan, user=user)

    async def write_step(self, *, user: str) -> StepScript:
        return await self.write_model(StepScript, user=user)
