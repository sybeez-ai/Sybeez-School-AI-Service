import asyncio

from src.modules.voice import agent
from src.providers.gemini_live import (
    TEACHING_FUNCTION_DECLARATIONS,
    build_gemini_live_setup,
    build_system_prompt,
)


class FakeLLM:
    def __init__(self, reply=None, boom=False):
        self.reply, self.boom, self.calls = reply, boom, 0

    async def complete(self, *, system, user):
        self.calls += 1
        if self.boom:
            raise RuntimeError("down")
        return self.reply


def run(coro):
    return asyncio.run(coro)


GOOD = (
    '{"steps":[{"say":"Fractions split a whole.","board":"1/2","tab":"board"},'
    '{"say":"Look at a pizza.","board":"","tab":"picture","picture_query":"fraction pizza"},'
    '{"say":"Spin it.","board":"","tab":"3d"}],"check_question":"What is half of 8?"}'
)


def test_plan_parses_and_downgrades_unsupported_3d():
    plan = run(agent.make_plan(FakeLLM(GOOD), topic="fractions", grade_band="elementary"))
    assert plan.source == "qwen"
    assert [s.tab for s in plan.steps] == ["board", "picture", "picture"]  # no 3D scene for fractions


def test_plan_keeps_3d_for_earth():
    plan = run(agent.make_plan(FakeLLM(GOOD), topic="day and night on Earth"))
    assert plan.steps[-1].tab == "3d"


def test_plan_falls_back_on_garbage_and_outage():
    assert run(agent.make_plan(FakeLLM("not json"), topic="photosynthesis")).source == "fallback"
    assert run(agent.make_plan(FakeLLM(boom=True), topic="photosynthesis")).source == "fallback"


def test_plan_rejects_unsafe_topic_without_calling_model():
    llm = FakeLLM(GOOD)
    try:
        run(agent.make_plan(llm, topic="how to make a bomb"))
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass
    assert llm.calls == 0


def test_text_answer_blocks_and_filters():
    llm = FakeLLM("Plants make food from light.")
    assert "can't help" in run(agent.text_answer(llm, message="how to hack a school", grade_band="middle"))
    assert llm.calls == 0
    assert run(agent.text_answer(llm, message="what is photosynthesis", grade_band="middle")).startswith("Plants")
    # unsafe model output is replaced
    bad = FakeLLM("here is porn")
    assert "can't help" in run(agent.text_answer(bad, message="what is photosynthesis", grade_band="middle"))


def test_setup_has_context_tools_and_safety():
    prompt = build_system_prompt("Class: 6B\nSubjects: Science", "elementary", "/student/learning")
    setup = build_gemini_live_setup(system_prompt=prompt)["setup"]
    text = setup["systemInstruction"]["parts"][0]["text"]
    assert "Class: 6B" in text and "elementary" in text and "child" in text
    names = {d["name"] for d in setup["tools"][0]["functionDeclarations"]}
    assert {"navigate_to_page", "teach_on_board", "set_learning_mode"} <= names
    assert len(names) == len(TEACHING_FUNCTION_DECLARATIONS)
    assert "keys" not in str(setup).lower()
