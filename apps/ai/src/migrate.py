"""Run Alembic and, on ECS, publish a redacted failure reason."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

from src.core.logging import redact


def failure_exit_code(output: str) -> int:
    """Map a migration failure onto an exit code the deploy log can show."""
    if "InvalidPasswordError" in output or "password authentication failed" in output:
        return 10
    if "InvalidCatalogNameError" in output:
        return 20
    if "InvalidAuthorizationSpecificationError" in output or "no pg_hba.conf" in output:
        return 17
    if "certificate verify failed" in output or "SSL" in output:
        return 12
    if "Connect call failed" in output or "ConnectionRefused" in output or "TimeoutError" in output:
        return 11
    if "ProgrammingError" in output or "InsufficientPrivilege" in output or "UndefinedTable" in output:
        return 13
    if "Could not configure the database URL" in output or "interpolation" in output:
        return 14
    if "ModuleNotFoundError" in output or "FileNotFoundError" in output:
        return 15
    if "OperationalError" in output:
        return 18
    return 19


def failure_reason(output: str) -> str:
    detail = redact(output)
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    interesting = [line for line in lines if "Database migration failed" in line or line.startswith("ERROR")]
    chosen = interesting[-1] if interesting else (lines[-1] if lines else "alembic failed")
    return chosen[:255]


def _task_identity() -> tuple[str, str, str] | None:
    uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get("ECS_CONTAINER_METADATA_URI")
    if not uri:
        return None
    try:
        with urllib.request.urlopen(uri + "/task", timeout=2) as response:
            payload = json.loads(response.read().decode())
        task_arn = str(payload["TaskARN"])
    except Exception:
        return None
    region = task_arn.split(":")[3]
    cluster = task_arn.split("/")[-2]
    return task_arn, cluster, region


def publish_reason(reason: str) -> None:
    """Store the reason where the deploy workflow already prints stoppedReason."""
    identity = _task_identity()
    if identity is None:
        return
    task_arn, cluster, region = identity
    try:
        import boto3

        boto3.client("ecs", region_name=region).stop_task(
            cluster=cluster,
            task=task_arn,
            reason=reason[:255],
        )
    except Exception:
        return


def main() -> int:
    try:
        proc = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    except Exception as exc:
        print(type(exc).__name__)
        return 15
    if proc.returncode == 0:
        return 0
    output = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    reason = failure_reason(output)
    print(reason)
    publish_reason(reason)
    return failure_exit_code(output)


if __name__ == "__main__":
    raise SystemExit(main())
