import hashlib
import secrets
import bcrypt

from app.core.config import get_settings

settings = get_settings()


def generate_api_token() -> str:
    random_part = secrets.token_urlsafe(32).replace("-", "").replace("_", "")
    return f"{settings.api_token_prefix}_{random_part}"


def generate_integration_token() -> str:
    random_part = secrets.token_urlsafe(48).replace("-", "").replace("_", "")
    return f"ia_int_{random_part}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
