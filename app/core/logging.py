import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.log_context import get_log_context

STANDARD_LOG_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


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
            "phase",
            "worker_name",
            "queue_job_id",
            "input_type",
            "processing_mode",
            "output_type",
            "parser_strategy",
            "formatter_strategy",
            "output_contract_source",
            "error_code",
            "error_category",
            "duration_seconds",
            "event",
            "status",
            "input_tokens",
            "output_tokens",
            "estimated_cost",
            "provider_calls",
            "input_file_count",
            "context_file_count",
            "chunk_index",
            "chunk_count",
            "row_index",
            "total_rows",
            "processed_rows",
            "successful_rows",
            "failed_rows",
            "header_count",
            "output_file_name",
            "output_file_mime",
            "output_file_size",
            "input_characters",
            "combined_characters",
            "context_characters",
            "retry_attempt",
            "delay_seconds",
        ]
        for key in enriched_keys:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        for key, value in record.__dict__.items():
            if key in payload:
                continue
            if key in STANDARD_LOG_RECORD_KEYS:
                continue
            if value is None:
                continue
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
