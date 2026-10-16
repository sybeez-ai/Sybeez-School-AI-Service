import json
import random
import re

from src.core.exceptions import AppError, UpstreamError
from src.modules.mcq.schemas import McqDraftQuestion, McqGenerateRequest, McqGenerateResponse
from src.providers.llm import EchoLLM, get_llm, guarded_complete
from src.shared.utils import load_prompt

_BANNED_OPTIONS = {"all of the above", "none of the above", "both a and b", "all of these", "none of these"}
_DIFFICULTIES = {"easy", "medium", "hard"}
_WORD = re.compile(r"[a-z0-9]+")


class McqNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__("AI question generation is not configured", code="ai_not_configured", status_code=503)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def similar(a: str, b: str, threshold: float = 0.8) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def extract_json(raw: str) -> object | None:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    for candidate in (text, *(m.group(0) for m in re.finditer(r"\{.*\}|\[.*\]", text, re.DOTALL))):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _items(data: object) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def validate_item(item: dict, n_options: int) -> McqDraftQuestion | None:
    prompt = str(item.get("prompt") or "").strip()
    options_raw = item.get("options")
    if not prompt or len(prompt) > 1000 or not isinstance(options_raw, list):
        return None
    options = [str(o).strip() for o in options_raw]
    if len(options) != n_options or any(not o or len(o) > 300 for o in options):
        return None
    lowered = [o.lower() for o in options]
    if len(set(lowered)) != len(lowered) or any(o.rstrip(".") in _BANNED_OPTIONS for o in lowered):
        return None
    idx = item.get("correct_index")
    if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(options):
        return None
    difficulty = str(item.get("difficulty") or "medium").lower()
    if difficulty not in _DIFFICULTIES:
        difficulty = "medium"
    tag = item.get("topic_tag")
    return McqDraftQuestion(
        prompt=prompt,
        options=options,
        correct_index=idx,
        explanation=str(item.get("explanation") or "").strip()[:1000],
        difficulty=difficulty,
        topic_tag=str(tag).strip()[:80] if tag else None,
    )


def shuffle_options(q: McqDraftQuestion, rng: random.Random) -> McqDraftQuestion:
    """Randomise option order so the key position is not a pattern; keep the key attached."""
    order = list(range(len(q.options)))
    rng.shuffle(order)
    return q.model_copy(update={"options": [q.options[i] for i in order], "correct_index": order.index(q.correct_index)})


class McqService:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.llm = get_llm()
        self.rng = rng or random.Random()

    def _user_prompt(self, body: McqGenerateRequest, count: int) -> str:
        lines = [
            f"Topic: {body.topic}",
            f"Subject: {body.subject_name or 'not specified'}",
            f"Class level: {body.class_label or 'not specified'}",
            f"Difficulty: {body.difficulty.value}",
            f"Number of questions: {count}",
            f"Options per question: {body.options_per_question}",
            f"Language: {body.language}",
        ]
        if body.source_notes:
            lines.append(f"<teacher_notes>\n{body.source_notes}\n</teacher_notes>")
        if body.avoid_prompts:
            lines.append("Questions to avoid:\n" + "\n".join(f"- {p}" for p in body.avoid_prompts))
        return "\n".join(lines)

    async def generate(self, body: McqGenerateRequest) -> McqGenerateResponse:
        if isinstance(self.llm, EchoLLM):
            raise McqNotConfigured()
        system = load_prompt("mcq/generate.txt")
        # Ask for a little extra so duplicates/invalid items can be dropped.
        ask = min(body.count + max(2, body.count // 4), 40)
        raw = await guarded_complete(self.llm, system=system, user=self._user_prompt(body, ask))
        data = extract_json(raw)
        if not _items(data):
            repair = (
                "The previous reply was not valid JSON in the required shape. Reply again with ONLY the JSON object.\n\n"
                + self._user_prompt(body, ask)
            )
            raw = await guarded_complete(self.llm, system=system, user=repair)
            data = extract_json(raw)
        items = _items(data)
        if not items:
            raise UpstreamError("The model did not return usable questions", code="mcq_generation_failed")

        valid: list[McqDraftQuestion] = []
        invalid = duplicates = 0
        seen = list(body.avoid_prompts)
        for item in items:
            q = validate_item(item, body.options_per_question)
            if q is None:
                invalid += 1
                continue
            if any(similar(q.prompt, other) for other in seen):
                duplicates += 1
                continue
            seen.append(q.prompt)
            valid.append(q)
        valid = valid[: body.count]
        if not valid:
            raise UpstreamError("The model did not return usable questions", code="mcq_generation_failed")
        if body.verify:
            valid = await self._verify(valid)
        valid = [shuffle_options(q, self.rng) for q in valid]
        return McqGenerateResponse(
            topic=body.topic,
            requested=body.count,
            questions=valid,
            dropped_invalid=invalid,
            dropped_duplicates=duplicates,
        )

    async def _verify(self, questions: list[McqDraftQuestion]) -> list[McqDraftQuestion]:
        """Blind-solve pass: flag questions where an independent answer disagrees with the key."""
        listing = "\n\n".join(
            f"Q{i + 1}. {q.prompt}\n" + "\n".join(f"  {j}. {o}" for j, o in enumerate(q.options))
            for i, q in enumerate(questions)
        )
        try:
            raw = await guarded_complete(self.llm, system=load_prompt("mcq/solve.txt"), user=listing)
        except UpstreamError:
            return [q.model_copy(update={"needs_review": True, "review_reason": "Not verified"}) for q in questions]
        data = extract_json(raw)
        answers = data.get("answers") if isinstance(data, dict) else None
        out: list[McqDraftQuestion] = []
        for i, q in enumerate(questions):
            if not isinstance(answers, list) or i >= len(answers):
                out.append(q.model_copy(update={"needs_review": True, "review_reason": "Not verified"}))
            elif answers[i] != q.correct_index:
                out.append(
                    q.model_copy(update={"needs_review": True, "review_reason": "Independent check chose a different answer"})
                )
            else:
                out.append(q)
        return out
