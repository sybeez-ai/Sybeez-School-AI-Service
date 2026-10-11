"""Load configuration from the process environment or AWS Secrets Manager.

ECS can inject Secrets Manager values as environment variables. When
AWS_SECRETS_MANAGER_SECRET_ID is set, the process also reads a JSON object at
startup. Explicit environment variables win, so task-definition secrets are not
overwritten. Secret values are never logged.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger("sybeez.ai.secrets")

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def apply_secret_mapping(payload: dict) -> bool:
    """Copy secret keys into the environment without overriding existing vars."""
    changed = False
    for key, value in payload.items():
        if not isinstance(key, str) or not _ENV_NAME.fullmatch(key):
            continue
        if isinstance(value, (dict, list)) or value is None:
            continue
        text = value if isinstance(value, str) else str(value)
        if "\x00" in text or "\n" in text or "\r" in text:
            continue
        if key in os.environ:
            continue
        os.environ[key] = text
        changed = True
    return changed


def fetch_secrets_manager_json(secret_id: str, region: str | None) -> dict:
    """Read one JSON secret. Raises RuntimeError without including the payload."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required to read Secrets Manager") from exc

    try:
        client = boto3.client("secretsmanager", region_name=region or None)
        response = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        logger.error("secrets manager read failed: %s", type(exc).__name__)
        raise RuntimeError("Could not read AWS_SECRETS_MANAGER_SECRET_ID") from exc

    raw = response.get("SecretString")
    if not raw and response.get("SecretBinary"):
        binary = response["SecretBinary"]
        raw = binary.decode("utf-8") if isinstance(binary, (bytes, bytearray)) else str(binary)
    if not raw:
        raise RuntimeError("Secrets Manager secret is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Secrets Manager secret must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Secrets Manager secret must be a JSON object")
    logger.info("loaded secret keys=%s", len(parsed))
    return parsed
