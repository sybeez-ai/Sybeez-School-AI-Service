import json
import logging
import re
import sys
from datetime import datetime, timezone

from src.core.request_context import request_id_var, school_id_var, user_id_var

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|password|secret|token|database_url)\b(\s*[:=]\s*)(\S+)"
)
_URL_RE = re.compile(
    r"(?i)\b(?:postgres(?:ql)?(?:\+[a-z0-9]+)?|mysql(?:\+[a-z0-9]+)?|mariadb(?:\+[a-z0-9]+)?"
    r"|rediss?|mongodb(?:\+srv)?|amqps?)://[^\s\"']+"
)
_IAM_RE = re.compile(
    r"(?i)(X-Amz-(?:Algorithm|Credential|Signature|Security-Token|Date|Expires|SignedHeaders)=)[^\s&\"']+"
)
_EXTRA_KEYS = ("method", "path", "status", "duration_ms", "row_school_id", "token_school_id")
_redaction_installed = False


def redact(message: object) -> str:
    text = message if isinstance(message, str) else str(message)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
    text = _URL_RE.sub("[redacted-url]", text)
    return _IAM_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)


class RedactFilter(logging.Filter):
    """Redact secrets before a formatter renders the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = redact(record.getMessage())
        except Exception:
            rendered = "[redacted]"
        record.msg = rendered
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_redaction() -> None:
    """Redact database URLs in every logging formatter, including Alembic's."""
    global _redaction_installed
    if not _redaction_installed:
        original = logging.Formatter.formatException

        def format_exception(self, ei):
            return redact(original(self, ei))

        logging.Formatter.formatException = format_exception
        _redaction_installed = True
    root = logging.getLogger()
    if not any(isinstance(existing, RedactFilter) for existing in root.filters):
        root.addFilter(RedactFilter())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_id_var.get(),
            "school_id": school_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key in _EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    install_redaction()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.propagate = True
