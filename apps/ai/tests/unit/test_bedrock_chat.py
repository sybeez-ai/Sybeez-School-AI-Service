"""Bedrock Converse mapping. No network call."""

import json

from botocore.exceptions import ClientError

from src.providers.bedrock_chat import (
    BedrockChatError,
    converse,
    from_converse,
    nova_lite_model_id,
    to_converse_messages,
    voice_engine,
)


def test_mumbai_uses_the_apac_nova_lite_profile_and_not_sonic():
    assert nova_lite_model_id("ap-south-1", "") == "apac.amazon.nova-lite-v1:0"
    assert nova_lite_model_id("us-east-1", "") == "us.amazon.nova-lite-v1:0"
    assert nova_lite_model_id("ap-south-1", "custom-model") == "custom-model"
    assert voice_engine("ap-south-1") == "transcribe-polly"
    assert voice_engine("us-east-1") == "nova-sonic"


def test_tool_results_become_converse_blocks():
    messages = [
        {"role": "user", "content": "show fractions"},
        {
            "role": "assistant",
            "content": "On the board.",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "show_board", "arguments": json.dumps({"text": "1/2"})},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "{\"ok\": true}"},
    ]
    converted = to_converse_messages(messages)
    assert converted[0]["role"] == "user"
    assert converted[1]["content"][1]["toolUse"]["name"] == "show_board"
    assert converted[1]["content"][1]["toolUse"]["input"] == {"text": "1/2"}
    assert converted[2]["content"][0]["toolResult"]["toolUseId"] == "call-1"


def test_converse_response_keeps_text_and_tool_calls():
    text, calls, usage, _model = from_converse({
        "output": {"message": {"content": [
            {"text": "Here it is."},
            {"toolUse": {"toolUseId": "t1", "name": "show_board", "input": {"text": "half"}}},
        ]}},
        "usage": {"inputTokens": 12, "outputTokens": 4},
    })
    assert text == "Here it is."
    assert calls[0]["function"]["name"] == "show_board"
    assert json.loads(calls[0]["function"]["arguments"]) == {"text": "half"}
    assert usage.input_tokens == 12 and usage.provider == "bedrock"


def test_access_denied_is_a_bedrock_error_without_the_request_body():
    from src.providers import bedrock_chat

    class Denied:
        def converse(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
                "Converse",
            )

    bedrock_chat._clients["ap-south-1"] = Denied()
    try:
        converse("system", [{"role": "user", "content": "secret prompt"}], [], model_id="m", region="ap-south-1")
    except BedrockChatError as exc:
        assert str(exc) == "AccessDeniedException"
        assert "secret prompt" not in str(exc)
    finally:
        bedrock_chat._clients.pop("ap-south-1", None)
