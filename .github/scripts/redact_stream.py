"""Redact database URLs from stdin. Used before a deploy step prints task output."""

import re
import sys

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


if __name__ == "__main__":
    sys.stdout.write(redact(sys.stdin.read()))
