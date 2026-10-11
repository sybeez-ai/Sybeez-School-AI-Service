"""Decision tests for the AI edge reconcile. No AWS calls."""

import unittest

from reconcile_ai_edge import (
    forward_target_groups,
    health_check_is_ready,
    ingress_allows,
    next_priority,
    record_names_load_balancer,
    select_host_rule,
)


TG = "arn:aws:elasticloadbalancing:ap-south-1:213433448375:targetgroup/sybeez-school-ai-tg/feaf650abcaba42d"
OTHER = "arn:aws:elasticloadbalancing:ap-south-1:213433448375:targetgroup/sybeez-school-api-tg/abc"


def rule(priority, host, target=TG, path=None, action="forward"):
    conditions = [{"Field": "host-header", "HostHeaderConfig": {"Values": [host]}}]
    if path:
        conditions.append({"Field": "path-pattern", "Values": [path]})
    actions = [{"Type": action, "TargetGroupArn": target}] if action == "forward" else [{"Type": action, "FixedResponseConfig": {"StatusCode": "503"}}]
    return {"Priority": str(priority), "IsDefault": False, "Conditions": conditions, "Actions": actions, "RuleArn": f"arn:rule/{priority}"}


class EdgeRules(unittest.TestCase):
    def test_selects_host_rule_that_covers_health(self):
        chosen = select_host_rule(
            [
                rule(10, "api.school.sybeez.ai", OTHER),
                rule(20, "ai.school.sybeez.ai", path="/teacher/*"),
                rule(30, "ai.school.sybeez.ai"),
            ],
            "ai.school.sybeez.ai",
        )
        self.assertEqual(chosen["Priority"], "30")

    def test_ignores_the_default_action(self):
        default = {"Priority": "default", "IsDefault": True, "Conditions": [], "Actions": [{"Type": "fixed-response"}]}
        self.assertIsNone(select_host_rule([default, rule(10, "api.school.sybeez.ai", OTHER)], "ai.school.sybeez.ai"))

    def test_fixed_response_rule_is_still_the_host_rule(self):
        chosen = select_host_rule([rule(12, "ai.school.sybeez.ai", action="fixed-response")], "ai.school.sybeez.ai")
        self.assertEqual(forward_target_groups(chosen), [])

    def test_priority_uses_the_next_free_slot(self):
        self.assertEqual(next_priority([rule(10, "api.school.sybeez.ai", OTHER), {"Priority": "default", "IsDefault": True}]), 11)

    def test_health_check_requires_the_ai_port_and_path(self):
        ready = {
            "Port": 8001,
            "HealthCheckProtocol": "HTTP",
            "HealthCheckPort": "traffic-port",
            "HealthCheckPath": "/health",
            "Matcher": {"HttpCode": "200"},
        }
        self.assertTrue(health_check_is_ready(ready))
        wrong = dict(ready, HealthCheckPath="/", HealthCheckProtocol="TCP")
        self.assertFalse(health_check_is_ready(wrong))

    def test_ingress_accepts_the_load_balancer_group_or_a_world_rule(self):
        permissions = [
            {"IpProtocol": "tcp", "FromPort": 8001, "ToPort": 8001, "UserIdGroupPairs": [{"GroupId": "sg-alb"}]},
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        ]
        self.assertTrue(ingress_allows(permissions, 8001, "sg-alb"))
        self.assertFalse(ingress_allows(permissions, 8001, "sg-other"))
        self.assertTrue(ingress_allows([{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}], 8001, "sg-other"))

    def test_alias_matches_the_load_balancer_name(self):
        record = {"Type": "A", "AliasTarget": {"DNSName": "dualstack.school-alb.ap-south-1.elb.amazonaws.com."}}
        self.assertTrue(record_names_load_balancer(record, "school-alb.ap-south-1.elb.amazonaws.com"))
        self.assertFalse(record_names_load_balancer({"Type": "A", "AliasTarget": {"DNSName": "other.elb.amazonaws.com"}}, "school-alb.ap-south-1.elb.amazonaws.com"))


if __name__ == "__main__":
    unittest.main()
