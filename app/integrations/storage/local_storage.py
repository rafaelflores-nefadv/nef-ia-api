from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def ensure_storage_root() -> Path:
    storage_path = Path(get_settings().storage_path)
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path
