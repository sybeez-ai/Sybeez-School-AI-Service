"""LangGraph flow for one student turn.

understand -> plan -> teach -> check, and on a later turn
understand -> grade -> adapt or the next step or summarise.
Internal trace notes stay on the state. Students receive chat text and board actions.
"""

import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from src.modules.teacher.fallback import build_plan, script_for_step, summary_script
from src.modules.teacher.protocol import LessonPlan, ProtocolError
from src.modules.teacher.safety import REFUSAL, assess
from src.modules.teacher.timeline import dumps_actions, time_script
from src.modules.teacher.writer import LessonWriter


class TeacherState(TypedDict, total=False):
    student_message: str
    grade_band: str
    context_block: str
    page_id: str
    needs_new_page: bool
    has_plan: bool
    awaiting_check: bool
    step_index: int
    attempt: int
    plan: dict
    expected_answer: str
    pending_expected: str
    check_prompt: str
    check_kind: str
    check_choices: list
    reexplain: bool
    phase: str
    status: str
    chat_text: str
    actions: list
    mastered_step: bool
    safety_refused: bool
    safety_redirect: bool
    safety_message: str
    trace: Annotated[list[str], operator.add]
    progress_updates: Annotated[list[dict], operator.add]


def normalise_answer(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (value or "").lower())).strip()


def answer_is_correct(expected: str, given: str) -> bool:
    exp = normalise_answer(expected)
    got = normalise_answer(given)
    if not exp or not got:
        return False
    if exp == got:
        return True
    exp_tokens = exp.split()
    got_tokens = got.split()
    if len(exp_tokens) == 1:
        return exp in got_tokens
    if exp in got:
        return True
    if not exp_tokens:
        return False
    overlap = len(set(exp_tokens) & set(got_tokens)) / len(set(exp_tokens))
    return overlap >= 0.6


def _step_prompt(state: TeacherState, plan: LessonPlan, step, reexplain: bool) -> str:
    pace = "Use shorter words and a new example." if reexplain else "Teach this step once."
    return (
        f"Grade band: {state.get('grade_band')}\n"
        f"Context:\n{state.get('context_block') or 'none'}\n"
        f"Topic: {plan.topic}\n"
        f"Step: {step.title}\nGoal: {step.goal}\n"
        f"Explanation to base this on: {step.explanation}\n"
        f"Check question: {step.check_prompt}\n"
        f"{pace} Return a step script JSON. page_id may be \"current\". "
        "Include narration. Do not reveal expected_answer inside chat."
    )


def build_teacher_graph(writer: LessonWriter):
    async def understand(state: TeacherState):
        decision = assess(
            state.get("student_message") or "",
            grade_band=state.get("grade_band") or "elementary",
            awaiting_check=bool(state.get("awaiting_check")) and bool(state.get("has_plan")),
        )
        return {
            "safety_refused": not decision.allowed,
            "safety_redirect": decision.redirect,
            "safety_message": decision.student_message,
            "trace": [f"understand:{decision.category}"],
        }

    async def plan_node(state: TeacherState):
        user = (
            f"Grade band: {state.get('grade_band')}\n"
            f"Student request: {state.get('student_message')}\n"
            f"Context:\n{state.get('context_block') or 'none'}\n"
            "Plan 3 short steps with goals, prerequisites, and a check question each. Return JSON only."
        )
        try:
            plan = await writer.write_plan(user=user)
        except ProtocolError:
            plan = build_plan(state.get("student_message") or "", grade_band=state.get("grade_band") or "elementary")
        return {
            "plan": plan.model_dump(mode="json"),
            "has_plan": True,
            "step_index": 0,
            "attempt": 0,
            "awaiting_check": False,
            "reexplain": False,
            "needs_new_page": bool(state.get("needs_new_page")),
            "status": "active",
            "phase": "plan",
            "trace": ["plan: steps goals prerequisites"],
        }

    async def teach(state: TeacherState):
        plan = LessonPlan.model_validate(state["plan"])
        index = min(int(state.get("step_index") or 0), len(plan.steps) - 1)
        step = plan.steps[index]
        reexplain = bool(state.get("reexplain"))
        try:
            script = await writer.write_step(user=_step_prompt(state, plan, step, reexplain))
        except ProtocolError:
            script = script_for_step(
                step,
                page_id=state.get("page_id") or "current",
                reexplain=reexplain,
                step_index=index,
                needs_new_page=bool(state.get("needs_new_page")) and index == 0,
                math="graph" in plan.topic.lower() or "function" in plan.topic.lower() or "equation" in plan.topic.lower(),
            )
        actions = time_script(script.chat, list(script.actions))
        return {
            "chat_text": script.chat,
            "actions": dumps_actions(actions),
            "check_prompt": script.check_prompt or step.check_prompt,
            "check_kind": script.check_kind,
            "check_choices": list(script.choices or step.choices),
            "pending_expected": script.expected_answer or step.expected_answer,
            "step_index": index,
            "phase": "teach",
            "reexplain": False,
            "trace": ["teach: explanation ready"],
        }

    async def check(state: TeacherState):
        chat = state.get("chat_text") or ""
        prompt = state.get("check_prompt") or ""
        if prompt and prompt not in chat:
            chat = f"{chat.rstrip()}\n\n{prompt}"
        return {
            "chat_text": chat,
            "awaiting_check": bool(prompt),
            "expected_answer": state.get("pending_expected") or "",
            "phase": "check" if prompt else state.get("phase") or "teach",
            "status": "active",
            "trace": ["check: question posed"],
        }

    async def grade(state: TeacherState):
        plan = state.get("plan") or {}
        steps = plan.get("steps") or [{}]
        index = min(int(state.get("step_index") or 0), len(steps) - 1)
        step = steps[index]
        correct = answer_is_correct(state.get("expected_answer") or "", state.get("student_message") or "")
        attempt = int(state.get("attempt") or 0)
        if not correct:
            attempt += 1
        return {
            "mastered_step": correct,
            "attempt": attempt,
            "step_index": index,
            "phase": "grade",
            "progress_updates": [
                {
                    "concept": step.get("title") or "step",
                    "status": "mastered" if correct else "needs_review",
                    "score": 1.0 if correct else 0.4,
                    "notes": "",
                }
            ],
            "trace": ["grade: matched" if correct else "grade: retry"],
        }

    async def adapt(state: TeacherState):
        return {
            "reexplain": True,
            "awaiting_check": False,
            "phase": "adapt",
            "trace": ["adapt: re-explain"],
        }

    async def advance(state: TeacherState):
        return {
            "step_index": int(state.get("step_index") or 0) + 1,
            "attempt": 0,
            "awaiting_check": False,
            "reexplain": False,
            "phase": "advance",
            "trace": ["advance: next step"],
        }

    async def summarise(state: TeacherState):
        plan = LessonPlan.model_validate(state["plan"])
        try:
            script = await writer.write_step(
                user=(
                    f"Summarise the lesson {plan.topic} for the student in a few sentences. "
                    "Return a step script with a new_page, write_text, and narration. "
                    "Leave check_prompt empty. Do not ask a new question."
                )
            )
        except ProtocolError:
            script = summary_script(plan, page_id=state.get("page_id") or "current")
        script = script.model_copy(update={"check_prompt": "", "expected_answer": ""})
        actions = time_script(script.chat, list(script.actions))
        return {
            "chat_text": script.chat,
            "actions": dumps_actions(actions),
            "check_prompt": "",
            "check_choices": [],
            "expected_answer": "",
            "pending_expected": "",
            "awaiting_check": False,
            "phase": "summarise",
            "status": "completed",
            "progress_updates": [
                {"concept": plan.topic, "status": "mastered", "score": 1.0, "notes": "lesson complete"}
            ],
            "trace": ["summarise: lesson closed"],
        }

    async def refuse(state: TeacherState):
        return {
            "chat_text": state.get("safety_message") or REFUSAL,
            "actions": [],
            "check_prompt": "",
            "check_choices": [],
            "awaiting_check": False,
            "phase": "refuse",
            "status": "active",
            "trace": ["refuse: blocked"],
        }

    async def redirect(state: TeacherState):
        return {
            "chat_text": state.get("safety_message") or "",
            "actions": [],
            "check_prompt": "",
            "check_choices": [],
            "awaiting_check": False,
            "phase": "redirect",
            "status": "active",
            "trace": ["redirect: back to school work"],
        }

    def after_understand(state: TeacherState) -> str:
        if state.get("safety_refused"):
            return "refuse"
        if state.get("safety_redirect"):
            return "redirect"
        finished = state.get("phase") == "summarise" or state.get("status") == "completed"
        if not state.get("has_plan") or finished:
            return "plan"
        if state.get("awaiting_check"):
            return "grade"
        return "teach"

    def after_grade(state: TeacherState) -> str:
        steps = (state.get("plan") or {}).get("steps") or []
        done = bool(state.get("mastered_step")) or int(state.get("attempt") or 0) >= 2
        if not done:
            return "adapt"
        if int(state.get("step_index") or 0) + 1 >= len(steps):
            return "summarise"
        return "advance"

    graph = StateGraph(TeacherState)
    graph.add_node("understand", understand)
    graph.add_node("plan", plan_node)
    graph.add_node("teach", teach)
    graph.add_node("check", check)
    graph.add_node("grade", grade)
    graph.add_node("adapt", adapt)
    graph.add_node("advance", advance)
    graph.add_node("summarise", summarise)
    graph.add_node("refuse", refuse)
    graph.add_node("redirect", redirect)
    graph.add_edge(START, "understand")
    graph.add_conditional_edges(
        "understand",
        after_understand,
        {"refuse": "refuse", "redirect": "redirect", "plan": "plan", "grade": "grade", "teach": "teach"},
    )
    graph.add_edge("plan", "teach")
    graph.add_edge("teach", "check")
    graph.add_edge("check", END)
    graph.add_conditional_edges(
        "grade",
        after_grade,
        {"adapt": "adapt", "advance": "advance", "summarise": "summarise"},
    )
    graph.add_edge("adapt", "teach")
    graph.add_edge("advance", "teach")
    graph.add_edge("summarise", END)
    graph.add_edge("refuse", END)
    graph.add_edge("redirect", END)
    return graph.compile()


async def run_teacher_turn(state: dict, llm) -> dict:
    graph = build_teacher_graph(LessonWriter(llm))
    return await graph.ainvoke(state)
