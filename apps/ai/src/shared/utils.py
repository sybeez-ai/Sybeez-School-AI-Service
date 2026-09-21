from datetime import UTC, datetime
from pathlib import Path


def utcnow() -> datetime:
    return datetime.now(UTC)


def load_prompt(relative: str) -> str:
    base = Path(__file__).resolve().parents[1] / "prompts"
    path = base / relative
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
