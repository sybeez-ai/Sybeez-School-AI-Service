import json
import logging
import re
import sys
from datetime import datetime, timezone

from src.core.request_context import request_id_var, school_id_var, user_id_var

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|password|secret|token|database_url)\b(\s*[:=]\s*)(\S+)"
)
_EXTRA_KEYS = ("method", "path", "status", "duration_ms", "row_school_id", "token_school_id")


def redact(message: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", message)


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
