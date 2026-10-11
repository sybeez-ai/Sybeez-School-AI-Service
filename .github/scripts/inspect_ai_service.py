"""Print why AI tasks stop. Omits environment values, secrets, and images hosts."""

from __future__ import annotations

import json
import re
import subprocess
import sys

CLUSTER = "sybeez-school-cluster"
SERVICE = "sybeez-school-ai"
REGION = "ap-south-1"


def aws(args: list[str]) -> dict:
    result = subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "aws failed").strip().splitlines()[-1][:400]
        print(f"denied {args[0]} {args[1]}: {detail}")
        return {}
    text = result.stdout.strip()
    return json.loads(text) if text else {}


def image_tag(image: str) -> str:
    return image.rsplit("/", 1)[-1] if image else ""


STARTUP_PROBE = r"""
import asyncio, sys
from src.core.config import get_settings, secret_is_insecure
code = 80
settings = get_settings()
if not settings.cognito_configured:
    code += 1
if settings.jwt_algorithm != "HS256" or secret_is_insecure(settings.jwt_secret):
    code += 2
if settings.core_internal_token == "dev-internal-service-token":
    code += 4
if "sybeez:sybeez@" in settings.database_url or not settings.database_url.strip():
    code += 8

async def role():
    global code
    from sqlalchemy import text
    from src.core.database import engine
    try:
        async with engine.connect() as connection:
            row = (await connection.execute(text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ))).one()
    except Exception:
        code += 16
        return
    if row[0]:
        code += 32
    elif row[1]:
        code += 64

asyncio.run(role())
raise SystemExit(code)
"""


def summarize_task_definition(label: str, task_def: str) -> None:
    described = aws(["ecs", "describe-task-definition", "--task-definition", task_def]).get("taskDefinition") or {}
    revision = described.get("revision")
    print(f"{label} revision={revision}")
    for container in described.get("containerDefinitions") or []:
        if container.get("name") != "ai":
            continue
        print(f"{label} image={image_tag(str(container.get('image') or ''))}")
        names = [str(item.get("name") or "") for item in container.get("environment") or []]
        print(f"{label} env={','.join(names)}")
        names = [str(item.get("name") or "") for item in container.get("secrets") or []]
        print(f"{label} secrets={','.join(names)}")


def probe_startup(service: dict, task_def: str) -> None:
    network = ((service.get("networkConfiguration") or {}).get("awsvpcConfiguration") or {})
    subnets = list(network.get("subnets") or [])
    groups = list(network.get("securityGroups") or [])
    if not subnets or not groups or not task_def:
        print("startup probe skipped: service network is incomplete")
        return
    overrides = json.dumps(
        {"containerOverrides": [{"name": "ai", "command": ["python", "-c", STARTUP_PROBE]}]}
    )
    public_ip = str(network.get("assignPublicIp") or "DISABLED")
    started = aws(
        [
            "ecs",
            "run-task",
            "--cluster",
            CLUSTER,
            "--task-definition",
            task_def,
            "--launch-type",
            "FARGATE",
            "--network-configuration",
            (
                "awsvpcConfiguration={subnets=["
                + ",".join(subnets)
                + "],securityGroups=["
                + ",".join(groups)
                + "],assignPublicIp="
                + public_ip
                + "}"
            ),
            "--overrides",
            overrides,
        ]
    )
    tasks = started.get("tasks") or []
    if not tasks:
        failures = started.get("failures") or []
        reason = failures[0].get("reason") if failures else "no task"
        print(f"startup probe was not started: {reason}")
        return
    task_arn = str(tasks[0].get("taskArn") or "")
    print(f"startup probe task={task_arn.rsplit('/', 1)[-1]} definition={task_def}")
    subprocess.run(
        ["aws", "ecs", "wait", "tasks-stopped", "--region", REGION, "--cluster", CLUSTER, "--tasks", task_arn],
        check=False,
    )
    described = aws(["ecs", "describe-tasks", "--cluster", CLUSTER, "--tasks", task_arn])
    for task in described.get("tasks") or []:
        for container in task.get("containers") or []:
            if container.get("name") == "ai":
                print(f"startup probe exit={container.get('exitCode')} stopped={task.get('stoppedReason')}")
                print(
                    "startup probe bits: +1 no cognito, +2 jwt rejected, +4 default core token, "
                    "+8 default database url, +16 database unreachable, +32 superuser, +64 bypassrls; base 80"
                )


def main() -> int:
    described = aws(["ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE])
    services = described.get("services") or []
    if not services:
        print("service was not returned")
        return 1
    service = services[0]
    print(
        f"service desired={service.get('desiredCount')} running={service.get('runningCount')} "
        f"pending={service.get('pendingCount')} status={service.get('status')}"
    )
    print(f"taskDefinition={service.get('taskDefinition')}")
    for deployment in service.get("deployments") or []:
        print(
            "deployment "
            f"status={deployment.get('status')} rollout={deployment.get('rolloutState')} "
            f"failed={deployment.get('failedTasks')} running={deployment.get('runningCount')} "
            f"desired={deployment.get('desiredCount')} task={deployment.get('taskDefinition')}"
        )
        reason = deployment.get("rolloutStateReason")
        if reason:
            print(f"deployment reason={reason}")
    for event in (service.get("events") or [])[:12]:
        print(f"event {event.get('message')}")

    task_def_arn = str(service.get("taskDefinition") or "")
    family_rev = task_def_arn.rsplit("/", 1)[-1]
    if family_rev:
        task_def = aws(["ecs", "describe-task-definition", "--task-definition", family_rev]).get("taskDefinition") or {}
        for container in task_def.get("containerDefinitions") or []:
            ports = [
                f"{item.get('containerPort')}/{item.get('protocol')}"
                for item in container.get("portMappings") or []
            ]
            print(
                f"container name={container.get('name')} image={image_tag(str(container.get('image') or ''))} "
                f"ports={','.join(ports) or 'none'} essential={container.get('essential')}"
            )
            command = container.get("command") or []
            if command:
                print("container command=" + " ".join(str(part) for part in command)[:300])

    task_ids = []
    for event in service.get("events") or []:
        for task_id in re.findall(r"\b[0-9a-f]{32}\b", str(event.get("message") or "")):
            if task_id not in task_ids:
                task_ids.append(task_id)
    if task_ids:
        arns = [f"arn:aws:ecs:{REGION}:213433448375:task/{CLUSTER}/{task_id}" for task_id in task_ids[:6]]
        described_tasks = aws(["ecs", "describe-tasks", "--cluster", CLUSTER, "--tasks", *arns])
        failures = described_tasks.get("failures") or []
        for failure in failures:
            print(f"task lookup {failure.get('arn', '').rsplit('/', 1)[-1]} reason={failure.get('reason')}")
        for task in described_tasks.get("tasks") or []:
            task_id = str(task.get("taskArn") or "").rsplit("/", 1)[-1]
            print(
                f"task {task_id} status={task.get('lastStatus')} health={task.get('healthStatus')} "
                f"stopped={task.get('stoppedReason')}"
            )
            for container in task.get("containers") or []:
                print(
                    f"task {task_id} container={container.get('name')} exit={container.get('exitCode')} "
                    f"reason={container.get('reason')}"
                )

    summarize_task_definition("running", str(service.get("taskDefinition") or ""))
    latest = aws(["ecs", "describe-task-definition", "--task-definition", "sybeez-school-ai"]).get("taskDefinition") or {}
    latest_arn = str(latest.get("taskDefinitionArn") or "")
    summarize_task_definition("latest", latest_arn or "sybeez-school-ai")
    probe_startup(service, latest_arn or str(service.get("taskDefinition") or ""))
    for desired in ("RUNNING", "STOPPED"):
        listed = aws(["ecs", "list-tasks", "--cluster", CLUSTER, "--service-name", SERVICE, "--desired-status", desired])
        arns = (listed.get("taskArns") or [])[:8]
        print(f"{desired.lower()} tasks={len(listed.get('taskArns') or [])}")
        if not arns:
            continue
        tasks = aws(["ecs", "describe-tasks", "--cluster", CLUSTER, "--tasks", *arns]).get("tasks") or []
        for task in tasks:
            task_id = str(task.get("taskArn") or "").rsplit("/", 1)[-1]
            print(
                f"task {task_id} status={task.get('lastStatus')} desired={task.get('desiredStatus')} "
                f"health={task.get('healthStatus')} stopped={task.get('stoppedReason')}"
            )
            for container in task.get("containers") or []:
                print(
                    f"task {task_id} container={container.get('name')} "
                    f"status={container.get('lastStatus')} exit={container.get('exitCode')} "
                    f"reason={container.get('reason')}"
                )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"inspect failed: {type(exc).__name__}")
        sys.exit(1)
