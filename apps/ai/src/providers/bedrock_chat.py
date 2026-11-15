"""Chat on Amazon Bedrock. Nova Lite via the Converse API. Gemini is not called.

ap-south-1 uses the APAC inference profile. Nova Sonic is not used: it is not
offered in Mumbai, and its languages do not include Hindi or the other Indian
languages the school hears. Those turns use Transcribe and Polly.
"""

from __future__ import annotations

import asyncio
import json
import logging

from botocore.exceptions import BotoCoreError, ClientError

from src.core.config import get_settings
from src.modules.usage.tokens import TokenUsage

logger = logging.getLogger("sybeez.ai.bedrock")

# Nova Sonic bidirectional speech is limited to these regions and to
# English, Spanish, French, Italian, and German. Mumbai is not one of them.
NOVA_SONIC_REGIONS = frozenset({"us-east-1", "us-west-2", "ap-northeast-1", "eu-north-1"})

_clients: dict[str, object] = {}


class BedrockChatError(Exception):
    """Bedrock refused or could not complete the call. The caller may try another provider."""


def nova_lite_model_id(region: str, override: str = "") -> str:
    chosen = (override or "").strip()
    if chosen:
        return chosen
    name = (region or "ap-south-1").strip()
    if name.startswith("eu-"):
        return "eu.amazon.nova-lite-v1:0"
    if name.startswith("us-"):
        return "us.amazon.nova-lite-v1:0"
    return "apac.amazon.nova-lite-v1:0"


def voice_engine(region: str) -> str:
    """Transcribe and Polly unless this region can run Nova Sonic."""
    if (region or "").strip() in NOVA_SONIC_REGIONS:
        return "nova-sonic"
    return "transcribe-polly"


def _client(region: str):
    key = region or "ap-south-1"
    cached = _clients.get(key)
    if cached is None:
        import boto3

        cached = boto3.client("bedrock-runtime", region_name=key)
        _clients[key] = cached
    return cached


def _schema(raw: object) -> dict:
    if isinstance(raw, dict) and raw.get("type") == "object":
        return raw
    return {"type": "object", "properties": {}}


def tool_config(declarations: list[dict]) -> dict | None:
    tools = []
    for item in declarations[:48]:
        name = str(item.get("name") or "")[:64]
        if not name or not name.replace("_", "").isalnum():
            continue
        spec: dict = {
            "name": name,
            "description": str(item.get("description") or name)[:600],
            "inputSchema": {"json": _schema(item.get("parameters"))},
        }
        tools.append({"toolSpec": spec})
    if not tools:
        return None
    return {"tools": tools}


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part) for part in content if part)
    return "" if content is None else str(content)


def to_converse_messages(messages: list[dict]) -> list[dict]:
    """OpenAI-style chat messages, including tool results, as Converse messages."""
    converted: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool":
            block = {
                "toolResult": {
                    "toolUseId": str(message.get("tool_call_id") or "tool")[:64],
                    "content": [{"text": _text(message.get("content"))[:4000] or "{}" }],
                }
            }
            if converted and converted[-1]["role"] == "user" and any("toolResult" in part for part in converted[-1]["content"]):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        blocks: list[dict] = []
        text = _text(message.get("content")).strip()
        if text:
            blocks.append({"text": text[:8000]})
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                try:
                    payload = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                blocks.append({
                    "toolUse": {
                        "toolUseId": str(call.get("id") or fn.get("name") or "tool")[:64],
                        "name": str(fn.get("name") or "")[:64],
                        "input": payload,
                    }
                })
        if not blocks:
            continue
        converse_role = "assistant" if role == "assistant" else "user"
        if converted and converted[-1]["role"] == converse_role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": converse_role, "content": blocks})
    return converted


def from_converse(response: dict) -> tuple[str, list[dict], TokenUsage, str]:
    message = (response.get("output") or {}).get("message") or {}
    text_parts: list[str] = []
    calls: list[dict] = []
    for block in message.get("content") or []:
        if block.get("text"):
            text_parts.append(str(block["text"]))
        tool = block.get("toolUse")
        if not tool:
            continue
        calls.append({
            "id": str(tool.get("toolUseId") or "")[:64],
            "type": "function",
            "function": {
                "name": str(tool.get("name") or "")[:64],
                "arguments": json.dumps(tool.get("input") or {}, ensure_ascii=False)[:4000],
            },
        })
    usage_raw = response.get("usage") or {}
    model = str(response.get("modelId") or response.get("model") or "")
    usage = TokenUsage(
        input_tokens=int(usage_raw.get("inputTokens") or 0),
        output_tokens=int(usage_raw.get("outputTokens") or 0),
        estimated=False,
        model=model or "nova-lite",
        provider="bedrock",
    )
    return " ".join(part.strip() for part in text_parts if part.strip()), calls[:6], usage, model


def converse(system: str, messages: list[dict], declarations: list[dict], *, model_id: str, region: str) -> dict:
    payload: dict = {
        "modelId": model_id,
        "messages": to_converse_messages(messages) or [{"role": "user", "content": [{"text": "Hello"}]}],
        "inferenceConfig": {"maxTokens": 800, "temperature": 0.3},
    }
    if system.strip():
        payload["system"] = [{"text": system[:12000]}]
    tools = tool_config(declarations)
    if tools:
        payload["toolConfig"] = tools
    try:
        return _client(region).converse(**payload)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code") or type(exc).__name__)
        logger.warning("bedrock converse failed: %s", code)
        raise BedrockChatError(code) from None
    except BotoCoreError as exc:
        logger.warning("bedrock converse failed: %s", type(exc).__name__)
        raise BedrockChatError(type(exc).__name__) from None


async def converse_reply(system: str, messages: list[dict], declarations: list[dict]) -> tuple[str, list[dict], TokenUsage, str]:
    settings = get_settings()
    region = (settings.aws_region or "").strip() or "ap-south-1"
    model_id = nova_lite_model_id(region, settings.bedrock_model_id)
    response = await asyncio.to_thread(
        converse, system, messages, declarations, model_id=model_id, region=region
    )
    text, calls, usage, returned = from_converse(response)
    if not usage.model or usage.model == "nova-lite":
        usage = TokenUsage(
            usage.input_tokens, usage.output_tokens, usage.estimated, model_id, "bedrock"
        )
    return text, calls, usage, returned or model_id
