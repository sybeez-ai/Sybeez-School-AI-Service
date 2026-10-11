"""Point ai.school.sybeez.ai at the AI target group and open the task port.

The public URL is served by the same application load balancer as the school
API. This only changes the AI host rule, the AI target group, the AI task
security group, and the AI DNS name. It does not update the API service.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOST = "ai.school.sybeez.ai"
TG_NAME = "sybeez-school-ai-tg"
CLUSTER = "sybeez-school-cluster"
SERVICE = "sybeez-school-ai"
PORT = 8001
REGION = "ap-south-1"
HEALTH_PATH = "/health"


class AwsError(RuntimeError):
    pass


def aws(args: list[str], *, region: str = REGION) -> dict:
    result = subprocess.run(
        ["aws", *args, "--region", region, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "aws command failed").strip()
        raise AwsError(detail.splitlines()[-1][:400])
    text = result.stdout.strip()
    if not text:
        return {}
    return json.loads(text)


def condition_values(condition: dict, config_key: str) -> list[str]:
    values = list(condition.get("Values") or [])
    config = condition.get(config_key) or {}
    values.extend(config.get("Values") or [])
    return [str(value) for value in values]


def rule_matches_host(rule: dict, host: str) -> bool:
    if rule.get("IsDefault"):
        return False
    wanted = host.lower().rstrip(".")
    for condition in rule.get("Conditions") or []:
        if str(condition.get("Field") or "").lower() != "host-header":
            continue
        hosts = {value.lower().rstrip(".") for value in condition_values(condition, "HostHeaderConfig")}
        if wanted in hosts:
            return True
    return False


def rule_covers_health_path(rule: dict) -> bool:
    for condition in rule.get("Conditions") or []:
        if str(condition.get("Field") or "").lower() != "path-pattern":
            continue
        patterns = condition_values(condition, "PathPatternConfig")
        if not any(pattern in {"*", "/*", "/health", "/health*"} for pattern in patterns):
            return False
    return True


def forward_target_groups(rule: dict) -> list[str]:
    found: list[str] = []
    for action in rule.get("Actions") or []:
        if str(action.get("Type") or "").lower() != "forward":
            continue
        direct = action.get("TargetGroupArn")
        if direct:
            found.append(str(direct))
        groups = (action.get("ForwardConfig") or {}).get("TargetGroups") or []
        for group in groups:
            arn = group.get("TargetGroupArn")
            if arn:
                found.append(str(arn))
    return found


def select_host_rule(rules: list[dict], host: str) -> dict | None:
    matches = [rule for rule in rules if rule_matches_host(rule, host)]
    for rule in matches:
        if rule_covers_health_path(rule):
            return rule
    return matches[0] if matches else None


def next_priority(rules: list[dict]) -> int:
    used: set[int] = set()
    for rule in rules:
        raw = str(rule.get("Priority") or "")
        if raw.isdigit():
            used.add(int(raw))
    if not used:
        return 10
    candidate = max(used) + 1
    if candidate <= 50000:
        return candidate
    for priority in range(1, 50000):
        if priority not in used:
            return priority
    raise AwsError("HTTPS listener has no free rule priority")


def health_check_is_ready(target_group: dict, *, port: int = PORT, path: str = HEALTH_PATH) -> bool:
    matcher = str((target_group.get("Matcher") or {}).get("HttpCode") or "")
    check_port = str(target_group.get("HealthCheckPort") or "")
    port_ok = check_port in {str(port), "traffic-port"} and int(target_group.get("Port") or 0) == port
    return (
        str(target_group.get("HealthCheckProtocol") or "").upper() == "HTTP"
        and port_ok
        and target_group.get("HealthCheckPath") == path
        and ("200" in {code.strip() for code in matcher.split(",")} or matcher in {"200", "200-299"})
    )


def ingress_allows(permissions: list[dict], port: int, source_group: str) -> bool:
    for permission in permissions:
        protocol = str(permission.get("IpProtocol") or "")
        if protocol not in {"tcp", "-1"}:
            continue
        if protocol == "tcp":
            start = int(permission.get("FromPort") or 0)
            end = int(permission.get("ToPort") or 0)
            if not start <= port <= end:
                continue
        pairs = permission.get("UserIdGroupPairs") or []
        if any(pair.get("GroupId") == source_group for pair in pairs):
            return True
        ranges = list(permission.get("IpRanges") or []) + list(permission.get("Ipv6Ranges") or [])
        for entry in ranges:
            cidr = entry.get("CidrIp") or entry.get("CidrIpv6")
            if cidr in {"0.0.0.0/0", "::/0"}:
                return True
    return False


def record_names_load_balancer(record: dict, load_balancer_dns: str) -> bool:
    alias_name = str((record.get("AliasTarget") or {}).get("DNSName") or "").lower().rstrip(".")
    wanted = load_balancer_dns.lower().rstrip(".")
    if not alias_name or not wanted:
        return False
    return alias_name in {wanted, f"dualstack.{wanted}"} or wanted == f"dualstack.{alias_name}"


def resolve_ips(hostname: str) -> set[str]:
    found: set[str] = set()
    for family in (socket.AF_INET,):
        try:
            infos = socket.getaddrinfo(hostname, 443, family)
        except socket.gaierror:
            continue
        for info in infos:
            found.add(info[4][0])
    return found


def load_balancer_for_host(load_balancers: list[dict], host_ips: set[str]) -> dict | None:
    for balancer in load_balancers:
        name = str(balancer.get("DNSName") or "")
        if name and resolve_ips(name) & host_ips:
            return balancer
    return None


def _print(message: str) -> None:
    print(message, flush=True)


def ensure_health_check(target_group: dict) -> None:
    arn = target_group["TargetGroupArn"]
    if health_check_is_ready(target_group):
        _print(f"target group {TG_NAME} health check is HTTP {HEALTH_PATH} on {PORT}")
        return
    _print(f"setting {TG_NAME} health check to HTTP {HEALTH_PATH} port {PORT}")
    aws(
        [
            "elbv2",
            "modify-target-group",
            "--target-group-arn",
            arn,
            "--health-check-protocol",
            "HTTP",
            "--health-check-port",
            str(PORT),
            "--health-check-path",
            HEALTH_PATH,
            "--matcher",
            "HttpCode=200",
            "--health-check-interval-seconds",
            "15",
            "--health-check-timeout-seconds",
            "5",
            "--healthy-threshold-count",
            "2",
            "--unhealthy-threshold-count",
            "3",
        ]
    )
    if int(target_group.get("Port") or 0) != PORT:
        aws(["elbv2", "modify-target-group", "--target-group-arn", arn, "--port", str(PORT)])


def ensure_ingress(task_group: str, source_groups: list[str]) -> None:
    described = aws(["ec2", "describe-security-groups", "--group-ids", task_group])
    groups = described.get("SecurityGroups") or []
    if not groups:
        raise AwsError("AI task security group was not found")
    permissions = groups[0].get("IpPermissions") or []
    for source in source_groups:
        if ingress_allows(permissions, PORT, source):
            _print(f"task security group allows {source} on tcp {PORT}")
            continue
        _print(f"allowing {source} to reach the AI task on tcp {PORT}")
        result = subprocess.run(
            [
                "aws",
                "ec2",
                "authorize-security-group-ingress",
                "--region",
                REGION,
                "--group-id",
                task_group,
                "--protocol",
                "tcp",
                "--port",
                str(PORT),
                "--source-group",
                source,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and "InvalidPermission.Duplicate" not in (result.stderr or ""):
            raise AwsError((result.stderr or "could not update the task security group").strip().splitlines()[-1][:400])


def ensure_host_rule(listener_arn: str, rules: list[dict], target_group_arn: str) -> None:
    rule = select_host_rule(rules, HOST)
    action = json.dumps([{"Type": "forward", "TargetGroupArn": target_group_arn}])
    if rule is None:
        priority = next_priority(rules)
        _print(f"creating host rule for {HOST} at priority {priority}")
        aws(
            [
                "elbv2",
                "create-rule",
                "--listener-arn",
                listener_arn,
                "--priority",
                str(priority),
                "--conditions",
                json.dumps([{"Field": "host-header", "Values": [HOST]}]),
                "--actions",
                action,
            ]
        )
        return
    targets = forward_target_groups(rule)
    if targets == [target_group_arn] and rule_covers_health_path(rule):
        _print(f"host rule for {HOST} already forwards to {TG_NAME}")
        return
    _print(f"updating host rule for {HOST} to forward to {TG_NAME}")
    conditions = json.dumps([{"Field": "host-header", "HostHeaderConfig": {"Values": [HOST]}}])
    aws(
        [
            "elbv2",
            "modify-rule",
            "--rule-arn",
            rule["RuleArn"],
            "--conditions",
            conditions,
            "--actions",
            action,
        ]
    )


def ensure_dns(hosted_zone_id: str, load_balancer: dict, records: list[dict]) -> None:
    name = HOST + "."
    wanted = str(load_balancer.get("DNSName") or "")
    existing = [
        record
        for record in records
        if str(record.get("Name") or "").lower().rstrip(".") == HOST and record.get("Type") in {"A", "AAAA", "CNAME"}
    ]
    if any(record_names_load_balancer(record, wanted) for record in existing):
        _print(f"DNS {HOST} already aliases this load balancer")
        return
    if existing and resolve_ips(HOST) and resolve_ips(wanted) and resolve_ips(HOST) == resolve_ips(wanted):
        _print(f"DNS {HOST} already resolves to this load balancer")
        return
    if not existing:
        _print(f"creating alias {HOST} to the AI load balancer")
    else:
        _print(f"updating alias {HOST} to the AI load balancer")
    change = {
        "Changes": [
            {
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": name,
                    "Type": "A",
                    "AliasTarget": {
                        "HostedZoneId": load_balancer["CanonicalHostedZoneId"],
                        "DNSName": wanted,
                        "EvaluateTargetHealth": False,
                    },
                },
            }
        ]
    }
    aws(
        [
            "route53",
            "change-resource-record-sets",
            "--hosted-zone-id",
            hosted_zone_id,
            "--change-batch",
            json.dumps(change),
        ]
    )


def wait_until_healthy(target_group_arn: str, attempts: int = 24, pause_seconds: float = 10) -> list[dict]:
    last: list[dict] = []
    for _ in range(attempts):
        described = aws(["elbv2", "describe-target-health", "--target-group-arn", target_group_arn])
        last = described.get("TargetHealthDescriptions") or []
        states = []
        for item in last:
            health = item.get("TargetHealth") or {}
            states.append(f"{health.get('State')}:{health.get('Reason') or 'ok'}")
        _print("target health " + (", ".join(states) if states else "no registered targets"))
        if any((item.get("TargetHealth") or {}).get("State") == "healthy" for item in last):
            return last
        time.sleep(pause_seconds)
    return last


def public_status(url: str, timeout: float = 15) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def https_listener(load_balancer_arn: str) -> tuple[str, list[dict]]:
    described = aws(["elbv2", "describe-listeners", "--load-balancer-arn", load_balancer_arn])
    listeners = described.get("Listeners") or []
    https = [
        item
        for item in listeners
        if int(item.get("Port") or 0) == 443 and str(item.get("Protocol") or "").upper() == "HTTPS"
    ]
    if not https:
        raise AwsError("the load balancer has no HTTPS listener on 443")
    listener_arn = str(https[0]["ListenerArn"])
    rules = aws(["elbv2", "describe-rules", "--listener-arn", listener_arn]).get("Rules") or []
    return listener_arn, rules


def wait_for_public_ok(attempts: int = 18, pause_seconds: float = 10) -> int:
    status = 0
    for _ in range(attempts):
        status = public_status(f"https://{HOST}{HEALTH_PATH}")
        _print(f"public https://{HOST}{HEALTH_PATH} status={status}")
        if status == 200:
            return status
        time.sleep(pause_seconds)
    return status


def main() -> int:
    try:
        groups = aws(["elbv2", "describe-target-groups", "--names", TG_NAME]).get("TargetGroups") or []
    except AwsError as exc:
        if "AccessDenied" not in str(exc) and "not authorized" not in str(exc).lower():
            raise
        _print(f"load balancer changes skipped: {exc}")
        return 0 if wait_for_public_ok() == 200 else 1
    groups = groups or []
    if not groups:
        raise AwsError(f"target group {TG_NAME} was not found")
    target_group = groups[0]
    target_group_arn = str(target_group["TargetGroupArn"])
    attached = target_group.get("LoadBalancerArns") or []
    _print(
        f"target group {TG_NAME} type={target_group.get('TargetType')} port={target_group.get('Port')} "
        f"health={target_group.get('HealthCheckProtocol')} {target_group.get('HealthCheckPath')} "
        f"attached={len(attached)}"
    )
    if target_group.get("TargetType") != "ip":
        raise AwsError(f"{TG_NAME} target type is {target_group.get('TargetType')}; Fargate registers ip targets")
    service = aws(
        ["ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE]
    ).get("services") or [{}]
    service = service[0]
    network = ((service.get("networkConfiguration") or {}).get("awsvpcConfiguration") or {})
    task_groups = list(network.get("securityGroups") or [])
    _print(
        f"ecs {SERVICE} desired={service.get('desiredCount')} running={service.get('runningCount')} "
        f"task_security_groups={','.join(task_groups) or 'none'}"
    )
    for event in (service.get("events") or [])[:5]:
        _print(f"ecs event {event.get('message')}")

    host_ips = resolve_ips(HOST)
    _print(f"dns {HOST} addresses={','.join(sorted(host_ips)) or 'none'}")
    balancers = aws(["elbv2", "describe-load-balancers"]).get("LoadBalancers") or []
    public = load_balancer_for_host(balancers, host_ips)
    if public is None:
        raise AwsError(f"no load balancer answers the addresses for {HOST}")
    public_arn = str(public["LoadBalancerArn"])
    _print(f"public load balancer {public.get('LoadBalancerName')} scheme={public.get('Scheme')}")
    if attached and public_arn not in attached:
        names = []
        for arn in attached:
            match = next((item for item in balancers if item.get("LoadBalancerArn") == arn), None)
            names.append(str((match or {}).get("LoadBalancerName") or arn))
        raise AwsError(
            f"{TG_NAME} is attached to {', '.join(names)}, which is not the load balancer for {HOST}"
        )

    ensure_health_check(target_group)
    if task_groups:
        ensure_ingress(task_groups[0], list(public.get("SecurityGroups") or []))
    else:
        _print("ecs service has no task security group; skipped ingress")

    listener_arn, rules = https_listener(public_arn)
    ensure_host_rule(listener_arn, rules, target_group_arn)

    try:
        zones = aws(["route53", "list-hosted-zones-by-name", "--dns-name", "school.sybeez.ai"]).get("HostedZones") or []
    except AwsError as exc:
        if "AccessDenied" not in str(exc) and "not authorized" not in str(exc).lower():
            raise
        _print(f"DNS lookup skipped: {exc}")
        zones = []
    zone = next((item for item in zones if str(item.get("Name") or "").rstrip(".") == "school.sybeez.ai"), None)
    if zone is None:
        _print("hosted zone school.sybeez.ai was not changed")
    else:
        listed = aws(["route53", "list-resource-record-sets", "--hosted-zone-id", zone["Id"]])
        ensure_dns(zone["Id"], public, listed.get("ResourceRecordSets") or [])

    wait_until_healthy(target_group_arn)
    status = public_status(f"https://{HOST}{HEALTH_PATH}")
    _print(f"public https://{HOST}{HEALTH_PATH} status={status}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AwsError as exc:
        print(f"edge reconcile failed: {exc}", file=sys.stderr)
        sys.exit(1)
