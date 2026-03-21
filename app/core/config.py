import json
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

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

    # Compatibilidade com formato antigo
    database_url: str | None = None
    shared_database_url: str | None = None
    sqlalchemy_echo: bool = False

    # Banco principal
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "nef_ia"

    # Banco compartilhado (opcional)
    shared_db_host: str | None = None
    shared_db_port: int | None = None
    shared_db_user: str | None = None
    shared_db_password: str | None = None
    shared_db_name: str | None = None

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
    allowed_file_extensions: list[str] = Field(default_factory=lambda: [".xlsx", ".csv", ".pdf"])
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
    anthropic_api_version: str = "2023-06-01"
    max_input_characters: int = 20000
    max_context_characters: int = 12000
    max_context_file_characters: int = 3500
    max_prompt_characters: int = 20000
    max_tokens_per_execution: int = 10000
    max_cost_per_execution: float = 10.0
    max_retries: int = 3
    max_execution_rows_hard_limit: int = 100000
    max_provider_calls_hard_limit: int = 10000
    max_text_chunks_hard_limit: int = 5000
    max_tabular_row_characters_hard_limit: int = 50000
    max_execution_seconds_hard_limit: int = 7200
    max_job_retries_hard_limit: int = 20
    retry_backoff: int = 2
    retry_backoff_seconds: int = 2
    max_concurrent_executions: int = 4
    chunk_size_characters: int = 8000
    execution_profile_default: str = "standard"
    execution_profile_automation_overrides: dict[str, str] = Field(default_factory=dict)
    execution_profile_standard_max_execution_rows: int = 25000
    execution_profile_standard_max_provider_calls: int = 2500
    execution_profile_standard_max_text_chunks: int = 1200
    execution_profile_standard_max_tabular_row_characters: int = 12000
    execution_profile_standard_max_execution_seconds: int = 1800
    execution_profile_standard_max_context_characters: int = 8000
    execution_profile_standard_max_context_file_characters: int = 2500
    execution_profile_standard_max_prompt_characters: int = 12000
    execution_profile_heavy_max_execution_rows: int = 60000
    execution_profile_heavy_max_provider_calls: int = 6000
    execution_profile_heavy_max_text_chunks: int = 3000
    execution_profile_heavy_max_tabular_row_characters: int = 30000
    execution_profile_heavy_max_execution_seconds: int = 5400
    execution_profile_heavy_max_context_characters: int = 11000
    execution_profile_heavy_max_context_file_characters: int = 3200
    execution_profile_heavy_max_prompt_characters: int = 18000
    execution_profile_extended_max_execution_rows: int = 90000
    execution_profile_extended_max_provider_calls: int = 9000
    execution_profile_extended_max_text_chunks: int = 4500
    execution_profile_extended_max_tabular_row_characters: int = 45000
    execution_profile_extended_max_execution_seconds: int = 6600
    execution_profile_extended_max_context_characters: int = 12000
    execution_profile_extended_max_context_file_characters: int = 3500
    execution_profile_extended_max_prompt_characters: int = 20000
    alert_failure_streak_threshold: int = 5
    alert_cost_threshold: float = 100.0
    alert_queue_stuck_minutes: int = 15

    @staticmethod
    def _build_pg_url(host: str, port: int, user: str, password: str, db_name: str) -> str:
        user_enc = quote_plus(user)
        password_enc = quote_plus(password)
        db_enc = quote_plus(db_name)
        return f"postgresql+psycopg://{user_enc}:{password_enc}@{host}:{port}/{db_enc}"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url and self.database_url.strip():
            return self.database_url.strip()
        return self._build_pg_url(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_password,
            db_name=self.db_name,
        )

    @property
    def resolved_shared_database_url(self) -> str:
        if self.shared_database_url and self.shared_database_url.strip():
            return self.shared_database_url.strip()

        if all(
            [
                self.shared_db_host,
                self.shared_db_port,
                self.shared_db_user,
                self.shared_db_password,
                self.shared_db_name,
            ]
        ):
            return self._build_pg_url(
                host=self.shared_db_host,
                port=self.shared_db_port,
                user=self.shared_db_user,
                password=self.shared_db_password,
                db_name=self.shared_db_name,
            )

        return self.resolved_database_url

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

    @field_validator("execution_profile_automation_overrides", mode="before")
    @classmethod
    def parse_execution_profile_overrides(cls, value: str | dict[str, str] | None) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return {
                str(key).strip().lower(): str(profile).strip().lower()
                for key, profile in value.items()
                if str(key).strip() and str(profile).strip()
            }
        raw = str(value).strip()
        if not raw:
            return {}

        parsed: dict[str, str] = {}
        if raw.startswith("{") and raw.endswith("}"):
            try:
                loaded = json.loads(raw)
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                for key, profile in loaded.items():
                    key_str = str(key).strip().lower()
                    profile_str = str(profile).strip().lower()
                    if key_str and profile_str:
                        parsed[key_str] = profile_str
                return parsed

        for item in raw.split(","):
            token = item.strip()
            if not token:
                continue
            if "=" in token:
                key, profile = token.split("=", 1)
            elif ":" in token:
                key, profile = token.split(":", 1)
            else:
                continue
            key_str = str(key).strip().lower()
            profile_str = str(profile).strip().lower()
            if key_str and profile_str:
                parsed[key_str] = profile_str
        return parsed

    @field_validator("execution_profile_default", mode="before")
    @classmethod
    def normalize_execution_profile_default(cls, value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        return normalized or "standard"

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.app_env == "production" and not (self.credentials_encryption_key or "").strip():
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
