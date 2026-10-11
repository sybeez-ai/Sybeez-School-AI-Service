"""Run Alembic and, on ECS, publish a redacted failure reason."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request

from src.core.logging import redact

# Exit code 100 + index. The deploy log prints the number; this list decodes it.
FAILURE_TYPES = (
    "ConnectionFailureError",
    "PostgresConnectionError",
    "ClientCannotConnectError",
    "CannotConnectNowError",
    "ConnectionRejectionError",
    "AdminShutdownError",
    "TooManyConnectionsError",
    "InvalidPasswordError",
    "InvalidCatalogNameError",
    "InvalidAuthorizationSpecificationError",
    "InsufficientPrivilegeError",
    "UndefinedTableError",
    "UndefinedObjectError",
    "DuplicateTableError",
    "DuplicateObjectError",
    "UniqueViolationError",
    "PostgresSyntaxError",
    "FeatureNotSupportedError",
    "DependentObjectsStillExistError",
    "ObjectInUseError",
    "ReadOnlySQLTransactionError",
    "DiskFullError",
    "OutOfMemoryError",
    "InternalClientError",
    "ProtocolViolationError",
    "ProgrammingError",
    "OperationalError",
    "InterfaceError",
    "IntegrityError",
    "ArgumentError",
    "CommandError",
    "InvalidRequestError",
    "StatementError",
    "DBAPIError",
    "RuntimeError",
    "TypeError",
    "ValueError",
    "OSError",
    "ModuleNotFoundError",
    "FileNotFoundError",
)


_COMMAND_PHRASES = (
    ("Can't locate revision", 40),
    ("Multiple head revisions", 41),
    ("more than one head", 42),
    ("Path doesn't exist", 43),
    ("script_location", 44),
    ("not up to date", 45),
    ("does not refer to ancestor", 46),
    ("No starting revision", 47),
    ("expected to be a sqlalchemy.engine.Connection", 48),
    ("expected to match one row", 49),
    ("Duplicate head", 50),
    ("Range revision not allowed", 51),
)


def failure_exit_code(output: str) -> int:
    """Map a migration failure onto an exit code the deploy log can show."""
    for phrase, code in _COMMAND_PHRASES:
        if phrase in output:
            return code
    if "Could not configure the database URL" in output:
        return 14
    if "certificate verify failed" in output:
        return 12
    match = re.search(r"Database migration failed \(([A-Za-z0-9_]+)\)", output)
    name = match.group(1) if match else ""
    if name not in FAILURE_TYPES:
        for candidate in FAILURE_TYPES:
            if candidate in output:
                name = candidate
                break
        else:
            name = ""
    if name in FAILURE_TYPES:
        return 100 + FAILURE_TYPES.index(name)
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
