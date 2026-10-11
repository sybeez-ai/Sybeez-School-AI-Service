"""Print redacted CloudWatch logs for the one-off Alembic ECS task."""

import json
import os
import re
import subprocess

_URL_RE = re.compile(
    r"(?i)\b(?:postgres(?:ql)?(?:\+[a-z0-9]+)?|mysql(?:\+[a-z0-9]+)?|rediss?|mongodb(?:\+srv)?|amqps?)://\S+"
)
_IAM_RE = re.compile(
    r"(?i)(X-Amz-(?:Algorithm|Credential|Signature|Security-Token|Date|Expires|SignedHeaders)=)[^\s&\"']+"
)
_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|password|secret|token|database_url)\b(\s*[:=]\s*)(\S+)"
)
_HOST_RE = re.compile(r"(?i)\b[\w.-]+\.rds\.amazonaws\.com(?::\d+)?\b")


def redact(text: str) -> str:
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
    text = _URL_RE.sub("[redacted-url]", text)
    text = _HOST_RE.sub("[redacted-host]", text)
    return _IAM_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)


def main() -> None:
    task_arn = os.environ.get("TASK_ARN", "")
    task_id = task_arn.rsplit("/", 1)[-1]
    container = os.environ.get("AWS_AI_CONTAINER", "ai")
    task_def = os.environ.get("TASK_DEF_ARN", "")
    raw = subprocess.check_output(
        [
            "aws",
            "ecs",
            "describe-task-definition",
            "--task-definition",
            task_def,
            "--query",
            "taskDefinition.containerDefinitions",
            "--output",
            "json",
        ],
        text=True,
    )
    containers = json.loads(raw)
    match = next((item for item in containers if item.get("name") == container), {})
    options = (match.get("logConfiguration") or {}).get("options") or {}
    group = options.get("awslogs-group")
    if not group:
        print("No awslogs group on the task definition.")
        return
    prefix = options.get("awslogs-stream-prefix", "ecs")
    region = options.get("awslogs-region") or os.environ.get("AWS_REGION") or "ap-south-1"
    stream = f"{prefix}/{container}/{task_id}"
    logs = subprocess.check_output(
        [
            "aws",
            "logs",
            "get-log-events",
            "--region",
            region,
            "--log-group-name",
            group,
            "--log-stream-name",
            stream,
            "--limit",
            "80",
            "--query",
            "events[].message",
            "--output",
            "json",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    print(f"Redacted migration logs from {group}:")
    for message in json.loads(logs):
        print(redact(str(message)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Could not read migration logs:", type(exc).__name__)
