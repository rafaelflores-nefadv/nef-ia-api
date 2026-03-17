import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.log_context import get_log_context


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        for key, value in get_log_context().items():
            if value is not None:
                payload[key] = value

        enriched_keys = [
            "execution_id",
            "request_id",
            "correlation_id",
            "provider",
            "model",
            "duration_seconds",
            "event",
            "status",
            "queue_job_id",
            "input_tokens",
            "output_tokens",
            "estimated_cost",
        ]
        for key in enriched_keys:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root_logger.addHandler(handler)

    logging.getLogger("uvicorn.error").handlers = [handler]
    logging.getLogger("uvicorn.access").handlers = [handler]
