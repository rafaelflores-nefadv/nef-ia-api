from enum import StrEnum


TABLE_PREFIX = "django_ai_"
AI_TABLE_PREFIX = TABLE_PREFIX


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    GENERATING_OUTPUT = "generating_output"
    COMPLETED = "completed"
    FAILED = "failed"
