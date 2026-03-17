from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "NEF IA API"
    app_env: Literal["local", "development", "staging", "production"] = "local"
    app_debug: bool = True
    api_prefix: str = "/api/v1"
    app_port: int = 8000

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nef_ia"
    shared_database_url: str | None = None
    sqlalchemy_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["none", "celery", "dramatiq"] = "dramatiq"
    queue_name: str = "nef_ia.executions"

    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    secret_key: str = "change-me"
    admin_jwt_algorithm: str = "HS256"
    admin_jwt_expire_minutes: int = 60
    api_token_prefix: str = "ia_live"
    credentials_encryption_key: str | None = None

    storage_path: str = "./storage"
    max_upload_size_mb: int = 1024
    upload_chunk_size_bytes: int = 1048576
    allowed_file_extensions: list[str] = Field(default_factory=lambda: [".xlsx", ".xls", ".csv", ".pdf"])
    allowed_file_mime_types: list[str] = Field(
        default_factory=lambda: [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "text/csv",
            "application/csv",
            "text/plain",
            "application/pdf",
            "application/octet-stream",
        ]
    )

    worker_prefetch_multiplier: int = 1
    worker_concurrency: int = 2
    max_tokens: int = 1500
    temperature: float = 0.2
    provider_timeout: int = 120
    provider_timeout_seconds: int = 120
    max_input_characters: int = 20000
    max_tokens_per_execution: int = 10000
    max_cost_per_execution: float = 10.0
    max_retries: int = 3
    retry_backoff: int = 2
    retry_backoff_seconds: int = 2
    max_concurrent_executions: int = 4
    chunk_size_characters: int = 8000
    alert_failure_streak_threshold: int = 5
    alert_cost_threshold: float = 100.0
    alert_queue_stuck_minutes: int = 15

    @property
    def resolved_shared_database_url(self) -> str:
        return self.shared_database_url or self.database_url

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if not value:
            return ["*"]
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @field_validator("allowed_file_extensions", "allowed_file_mime_types", mode="before")
    @classmethod
    def parse_csv_list(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [item.strip() for item in value if item and item.strip()]
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.app_env == "production" and not (self.credentials_encryption_key or "").strip():
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
