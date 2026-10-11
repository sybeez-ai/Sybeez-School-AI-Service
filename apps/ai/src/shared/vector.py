import math
from uuid import UUID


def vector_literal(values: list[float]) -> str:
    """Build a pgvector literal from numbers. The result is bound, never interpolated."""
    if not isinstance(values, list) or not values:
        raise ValueError("embedding required")
    if len(values) > 8192:
        raise ValueError("embedding too long")
    parts: list[str] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("embedding must be finite")
        parts.append(format(number, ".8g"))
    literal = "[" + ",".join(parts) + "]"
    if any(token in literal for token in ("'", ";", "--", "/*")):
        raise ValueError("embedding literal rejected")
    return literal


def clamp_limit(limit: int, *, maximum: int = 20) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 1
    return max(1, min(value, maximum))


def same_uuid(value: object, expected: UUID) -> bool:
    if value is None:
        return False
    try:
        return UUID(str(value)) == expected
    except (TypeError, ValueError):
        return False
