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


def test_an_assigned_model_replaces_the_chat_model():
    llm = type("Provider", (), {})()
    llm.model = "default-model"
    llm.candidates = [("echo", "key", "https://example.test", "default-model")]
    token = allowance_var.set(TokenAllowance(True, None, "school-model"))
    try:
        assert pin_model(llm) is None
    finally:
        allowance_var.reset(token)
    assert llm.model == "school-model"
    assert llm.candidates[0][3] == "school-model"
