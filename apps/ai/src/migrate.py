"""Run Alembic and, on ECS, publish a redacted failure reason."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

from src.core.logging import redact


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
    proc = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if proc.returncode == 0:
        return 0
    reason = failure_reason(f"{proc.stderr or ''}\n{proc.stdout or ''}")
    print(reason)
    publish_reason(reason)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
