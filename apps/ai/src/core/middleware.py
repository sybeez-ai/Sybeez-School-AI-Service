import asyncio
import logging
import time
import uuid

from src.core.config import get_settings
from src.core.exceptions import AppError, error_body
from src.core.rate_limit import limiter
from src.core.request_context import request_id_var, school_id_var, user_id_var
from src.core.security import AuthContext, authenticate_token

logger = logging.getLogger("sybeez.ai.access")

_HEALTH_PATHS = {"/health", "/ready", "/api/v1/ai/health", "/api/v1/ai/ready"}
_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class BodyTooLarge(Exception):
    pass


def normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def request_timeout_for_path(path: str) -> float:
    """Lesson playback and chat streams outlive a normal JSON request."""
    settings = get_settings()
    normalized = normalize_path(path)
    if normalized == "/api/v1/ai/chat" or normalized.startswith("/api/v1/ai/teacher"):
        return settings.stream_timeout_seconds
    return settings.request_timeout_seconds


def is_public_path(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    normalized = normalize_path(path)
    if normalized in _HEALTH_PATHS:
        return True
    settings = get_settings()
    if settings.app_env != "production" and (
        normalized in {"/docs", "/redoc", "/openapi.json"} or normalized.startswith("/docs/")
    ):
        return True
    return False


def header_value(scope: dict, name: str) -> str | None:
    target = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode("latin-1")
    return None


def client_ip(scope: dict) -> str:
    settings = get_settings()
    if settings.client_trusts_proxy():
        forwarded = header_value(scope, "x-forwarded-for")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return "unknown"


class InvalidContentLength(Exception):
    pass


def _declared_length(scope: dict) -> int | None:
    raw = header_value(scope, "content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise InvalidContentLength() from exc
    if value < 0:
        raise InvalidContentLength()
    return value


async def buffer_receive(receive, method: str, max_bytes: int, declared: int | None):
    if method not in _BODY_METHODS:
        return receive
    if declared is not None and declared > max_bytes:
        raise BodyTooLarge()
    buffered: list[dict] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.request":
            total += len(message.get("body") or b"")
            if total > max_bytes:
                raise BodyTooLarge()
        buffered.append(message)
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request" or not message.get("more_body", False):
            break
    pending = list(buffered)

    async def replay():
        if pending:
            return pending.pop(0)
        # After the body, wait for the real disconnect. A fake request message
        # here makes StreamingResponse poll forever.
        return await receive()

    return replay


async def send_json(send, status: int, payload: dict, request_id: str, extra: list[tuple[bytes, bytes]] | None = None):
    import json

    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"x-request-id", request_id.encode()),
    ]
    if extra:
        headers.extend(extra)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        request_id = header_value(scope, "x-request-id") or str(uuid.uuid4())
        path = normalize_path(scope.get("path", ""))
        method = scope.get("method", "GET")
        started = time.perf_counter()
        response_started = False
        status_holder = {"code": 500}
        bindings = [
            (request_id_var, request_id_var.set(request_id)),
            (school_id_var, school_id_var.set("-")),
            (user_id_var, user_id_var.set("-")),
        ]

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_holder["code"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            rejection = await self._gate(scope, path, method, bindings)
            if rejection is not None:
                status, payload, extra = rejection
                status_holder["code"] = status
                await send_json(send, status, payload, request_id, extra)
                return

            timeout = request_timeout_for_path(path)

            async def run():
                declared = _declared_length(scope)
                downstream = await buffer_receive(receive, method, settings.max_body_bytes, declared)
                await self.app(scope, downstream, send_wrapper)

            await asyncio.wait_for(run(), timeout=timeout)
        except BodyTooLarge:
            status_holder["code"] = 413
            if not response_started:
                await send_json(send, 413, error_body("payload_too_large", "Request body too large"), request_id)
        except InvalidContentLength:
            status_holder["code"] = 400
            if not response_started:
                await send_json(send, 400, error_body("bad_request", "Invalid content length"), request_id)
        except TimeoutError:
            logger.warning("request timed out", extra={"method": method, "path": path})
            status_holder["code"] = 504
            if not response_started:
                await send_json(send, 504, error_body("timeout", "Request timed out"), request_id)
        except Exception:
            logger.exception("request failed", extra={"method": method, "path": path})
            status_holder["code"] = 500
            if not response_started:
                await send_json(send, 500, error_body("internal_error", "Internal server error"), request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log = logger.debug if path in _HEALTH_PATHS else logger.info
            log(
                "request completed",
                extra={"method": method, "path": path, "status": status_holder["code"], "duration_ms": duration_ms},
            )
            for var, token in reversed(bindings):
                var.reset(token)

    async def _gate(self, scope, path: str, method: str, bindings: list):
        if path not in _HEALTH_PATHS and method != "OPTIONS":
            ip = client_ip(scope)
            if not await limiter.allow(f"ip:{ip}"):
                logger.warning("rate limit exceeded", extra={"path": path, "status": 429})
                return 429, error_body("rate_limited", "Too many requests"), [(b"retry-after", b"60")]

        if is_public_path(path, method):
            return None

        authorization = header_value(scope, "authorization")
        if not authorization or not authorization.lower().startswith("bearer "):
            return 401, error_body("unauthorized", "Missing bearer token"), None
        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return 401, error_body("unauthorized", "Missing bearer token"), None
        try:
            ctx = await authenticate_token(token)
        except AppError as exc:
            logger.warning("authentication failed", extra={"path": path, "status": exc.status_code})
            return exc.status_code, error_body(exc.code, exc.message), None
        if not isinstance(ctx, AuthContext) or ctx.school_id is None:
            return 403, error_body("forbidden", "School context required"), None

        bindings.append((school_id_var, school_id_var.set(str(ctx.school_id))))
        bindings.append((user_id_var, user_id_var.set(str(ctx.user_id))))
        if not await limiter.allow(f"user:{ctx.user_id}"):
            logger.warning("user rate limit exceeded", extra={"path": path, "status": 429})
            return 429, error_body("rate_limited", "Too many requests"), [(b"retry-after", b"60")]

        state = scope.setdefault("state", {})
        state["auth"] = ctx
        state["token"] = token
        return None
