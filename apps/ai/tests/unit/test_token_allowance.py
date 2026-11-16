import asyncio

from src.modules.usage.allowance import TokenAllowance, allowance_var, pin_model
from src.providers.llm import EchoLLM


def test_a_reached_limit_is_the_reply_and_does_not_record_usage():
    token = allowance_var.set(TokenAllowance(False, "Monthly limit reached.", "gemini"))
    try:
        llm = EchoLLM()
        text = asyncio.run(llm.complete(system="s", user="hello"))
    finally:
        allowance_var.reset(token)
    assert text == "Monthly limit reached."
    assert getattr(llm, "usages", None) in (None, [])


def test_an_assigned_qwen_model_replaces_the_chat_model():
    llm = type("Provider", (), {})()
    llm.model = "default-model"
    llm.candidates = [("qwen", "key", "https://example.test", "default-model")]
    token = allowance_var.set(TokenAllowance(True, None, "qwen3.8-flash"))
    try:
        assert pin_model(llm) is None
    finally:
        allowance_var.reset(token)
    assert llm.model == "qwen3.8-flash"
    assert llm.candidates[0][3] == "qwen3.8-flash"


def test_a_gemini_assignment_does_not_move_chat_off_qwen():
    llm = type("Provider", (), {})()
    llm.model = "qwen3.8-flash"
    llm.candidates = [("qwen", "key", "https://example.test", "qwen3.8-flash")]
    token = allowance_var.set(TokenAllowance(True, None, "gemini"))
    try:
        assert pin_model(llm) is None
    finally:
        allowance_var.reset(token)
    assert llm.model == "qwen3.8-flash"
    assert llm.candidates[0][3] == "qwen3.8-flash"
