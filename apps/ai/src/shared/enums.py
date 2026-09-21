from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    STRUGGLE = "struggle"
    SUCCESS = "success"
    STYLE = "style"
    CONCEPT = "concept"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class PracticeDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    ADAPTIVE = "adaptive"


class LearningMode(StrEnum):
    BOARD = "board"
    THREE_D = "3d"
    PICTURE = "picture"
