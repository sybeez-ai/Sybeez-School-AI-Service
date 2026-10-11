"""Deterministic lesson used when the model output fails the board schema.

The script is still a real explanation with whiteboard actions, not the raw model text.
"""

import re
import uuid

from src.modules.teacher.protocol import (
    ClearRegion,
    DrawShape,
    Highlight,
    LessonPlan,
    LessonStep,
    Narration,
    NewPage,
    PlaceIcon,
    PlaceImage,
    PlotFunction,
    Point,
    StepScript,
    WriteMath,
    WriteText,
    prepare_actions,
)

_LEADING = re.compile(
    r"^(please\s+)?(can you\s+)?(teach me( about)?|explain|help me understand|what is|what's|what was|how does|how do)\s+",
    re.IGNORECASE,
)
_STOP = frozenset({"the", "a", "an", "of", "to", "and", "in", "on", "for", "me", "about", "please"})


def infer_topic(message: str) -> str:
    cleaned = _LEADING.sub("", (message or "").strip()).strip(" ?.!")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rsplit(" ", 1)[0]
    return cleaned or "this idea"


def key_phrase(topic: str) -> str:
    words = [word for word in re.findall(r"[a-z0-9]+", topic.lower()) if word not in _STOP]
    return " ".join(words[:3]) or "the idea"


def _is_fraction(text: str) -> bool:
    return bool(re.search(r"fraction|numerator|denominator|one half", text, re.IGNORECASE))


def _looks_math(text: str) -> bool:
    return bool(re.search(r"\b(graph|function|equation|algebra|plot|triangle|area)\b", text, re.IGNORECASE))


def build_plan(message: str, *, grade_band: str) -> LessonPlan:
    topic = infer_topic(message)
    if _is_fraction(f"{topic} {message}"):
        return _fraction_plan()
    phrase = key_phrase(topic)
    math = _looks_math(f"{topic} {message}")
    band = "short sentences" if grade_band == "elementary" else "clear classroom language"
    return LessonPlan(
        topic=topic,
        goals=[
            f"Say what {phrase} means",
            f"Look at one example of {phrase}",
            f"Answer a question about {phrase}",
        ],
        prerequisites=[f"Words from class about {phrase}. Use {band}."],
        steps=[
            LessonStep(
                title=f"What {phrase} means",
                goal=f"Name {phrase}",
                explanation=(
                    f"{topic[0].upper() + topic[1:]} is the idea we are learning. "
                    f"Keep the words {phrase} in mind. We will start with the meaning, then one example."
                ),
                example=phrase,
                check_prompt=f"What idea are we learning? Answer with: {phrase}",
                expected_answer=phrase,
                board="intro",
            ),
            LessonStep(
                title="One example",
                goal=f"See {phrase} in an example",
                explanation=(
                    f"Here is one example of {phrase}. Follow the arrow from the name to the example. "
                    f"The example uses the same idea, just in a smaller case."
                ),
                example=f"Example of {phrase}",
                check_prompt="The arrow points from the name to the example. What does the arrow connect? Answer: example",
                expected_answer="example",
                board="example",
            ),
            LessonStep(
                title="Your turn",
                goal=f"Use {phrase} in one sentence",
                explanation=(
                    f"Your turn. Say one sentence that uses {phrase}. "
                    + ("A simple curve y = x squared is only a picture of change, not the answer itself. " if math else "")
                    + "If you can say the idea in your own words, you have it."
                ),
                example=phrase,
                check_prompt=f"Finish this: we are learning about {phrase}. Answer with the topic word.",
                check_kind="ask",
                expected_answer=phrase.split()[0],
                board="practice",
            ),
        ],
    )


def _fraction_plan() -> LessonPlan:
    return LessonPlan(
        topic="fractions",
        goals=[
            "Name the denominator and numerator",
            "See one half on the board",
            "Read the numerator in three quarters",
        ],
        prerequisites=["Equal parts of a whole, from class."],
        steps=[
            LessonStep(
                title="What a fraction is",
                goal="Say what the denominator tells us",
                explanation=(
                    "A fraction names equal parts of a whole. The bottom number is the denominator. "
                    "It tells how many equal parts. The top number is the numerator. It tells how many of those parts we have. "
                    "One half is 1 over 2, so the denominator is 2."
                ),
                example="1/2",
                check_prompt="What is the denominator in one half?",
                expected_answer="2",
                board="intro",
            ),
            LessonStep(
                title="See one half",
                goal="Picture one half as one of two equal parts",
                explanation=(
                    "If a shape is split into two equal parts and one part is shaded, the shaded part is one half. "
                    "The arrow points at the shaded part."
                ),
                example="one of two equal parts",
                check_prompt="A half splits a whole into how many equal parts? Answer with: two",
                expected_answer="two",
                board="example",
            ),
            LessonStep(
                title="Three quarters",
                goal="Read the numerator",
                explanation=(
                    "Three quarters means 3 parts out of 4 equal parts. The numerator is the top number, 3."
                ),
                example="3/4",
                check_prompt="What is the numerator in three quarters?",
                expected_answer="3",
                board="practice",
            ),
        ],
    )


def script_for_step(
    step: LessonStep,
    *,
    page_id: str,
    reexplain: bool,
    step_index: int,
    needs_new_page: bool,
    math: bool,
) -> StepScript:
    title_id = str(uuid.uuid4())
    actions = []
    if step_index > 0 or needs_new_page:
        actions.append(NewPage(page_id=str(uuid.uuid4()), title=step.title))
        page_id = actions[0].page_id
    lead = "Let's slow down. " if reexplain else ""
    chat = f"{lead}{step.explanation}"
    if reexplain:
        actions.append(ClearRegion(page_id=page_id, x=0.05, y=0.05, w=0.9, h=0.9))
    actions.append(WriteText(id=title_id, page_id=page_id, text=step.title, x=0.08, y=0.1, size="lg"))
    actions.append(WriteText(page_id=page_id, text=step.explanation, x=0.08, y=0.22, size="md"))
    if step.board == "intro":
        actions.append(PlaceIcon(page_id=page_id, library="lucide", name="lightbulb", x=0.8, y=0.1))
        if _is_fraction(step.explanation):
            actions.append(WriteMath(page_id=page_id, latex=r"\frac{1}{2}", x=0.08, y=0.48))
    elif step.board == "example":
        actions.append(
            DrawShape(
                page_id=page_id,
                shape="arrow",
                points=[Point(x=0.12, y=0.55), Point(x=0.42, y=0.55)],
            )
        )
        actions.append(
            PlaceImage(
                page_id=page_id,
                source="searched",
                query=step.title,
                alt=step.explanation[:180],
                x=0.58,
                y=0.4,
            )
        )
        if _is_fraction(step.explanation):
            actions.append(DrawShape(page_id=page_id, shape="circle", x=0.2, y=0.72, r=0.08))
    elif step.board == "practice":
        actions.append(Highlight(page_id=page_id, target_id=title_id))
        if _is_fraction(step.explanation):
            actions.append(WriteMath(page_id=page_id, latex=r"\frac{3}{4}", x=0.08, y=0.48))
        elif math:
            actions.append(PlotFunction(page_id=page_id, expression="x^2", x_min=-4, x_max=4))
    if step.check_prompt:
        actions.append(WriteText(page_id=page_id, text=step.check_prompt, x=0.08, y=0.84, size="sm"))
    actions.append(Narration(page_id=page_id, text=chat))
    script = StepScript(
        chat=chat,
        actions=prepare_actions(actions),
        check_prompt=step.check_prompt,
        check_kind=step.check_kind,
        choices=list(step.choices),
        expected_answer=step.expected_answer,
    )
    return script


def summary_script(plan: LessonPlan, *, page_id: str) -> StepScript:
    lines = [f"You worked through {plan.topic}."]
    lines.extend(f"You can {goal[0].lower() + goal[1:]}" if goal else goal for goal in plan.goals)
    chat = " ".join(lines)
    new_page = NewPage(page_id=str(uuid.uuid4()), title="Summary")
    actions = [
        new_page,
        WriteText(page_id=new_page.page_id, text=f"Summary: {plan.topic}", x=0.08, y=0.12, size="lg"),
        WriteText(page_id=new_page.page_id, text=" ".join(plan.goals), x=0.08, y=0.28),
        PlaceIcon(page_id=new_page.page_id, library="lucide", name="check", x=0.8, y=0.12),
        Narration(page_id=new_page.page_id, text=chat),
    ]
    return StepScript(chat=chat, actions=prepare_actions(actions), check_prompt="", expected_answer="")
