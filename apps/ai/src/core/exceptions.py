from fastapi import status


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class AppError(Exception):
    def __init__(self, message: str, code: str = "app_error", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found", code: str = "not_found"):
        super().__init__(message, code=code, status_code=status.HTTP_404_NOT_FOUND)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden", code: str = "forbidden"):
        super().__init__(message, code=code, status_code=status.HTTP_403_FORBIDDEN)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized", code: str = "unauthorized"):
        super().__init__(message, code=code, status_code=status.HTTP_401_UNAUTHORIZED)


class UpstreamError(AppError):
    def __init__(self, message: str = "Upstream request failed", code: str = "upstream_error"):
        super().__init__(message, code=code, status_code=status.HTTP_502_BAD_GATEWAY)


class RateLimitError(AppError):
    def __init__(self, message: str = "Too many requests"):
        super().__init__(message, code="rate_limited", status_code=status.HTTP_429_TOO_MANY_REQUESTS)


class RequestTimeoutError(AppError):
    def __init__(self, message: str = "Request timed out"):
        super().__init__(message, code="timeout", status_code=status.HTTP_504_GATEWAY_TIMEOUT)


class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "Request body too large"):
        super().__init__(message, code="payload_too_large", status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
