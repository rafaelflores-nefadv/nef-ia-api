from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.exceptions import AppException


FERNET_PREFIX = "fernet:"
LEGACY_PREFIXES = ("base64:", "plain:")


def encrypt_secret(raw_value: str) -> str:
    normalized = raw_value.strip()
    if not normalized:
        raise AppException(
            "Secret value cannot be empty.",
            status_code=422,
            code="secret_value_empty",
        )
    cipher = _get_cipher()
    encrypted = cipher.encrypt(normalized.encode("utf-8")).decode("utf-8")
    return f"{FERNET_PREFIX}{encrypted}"


def decrypt_secret(encrypted_value: str) -> str:
    normalized = encrypted_value.strip()
    if not normalized:
        raise AppException(
            "Encrypted secret value is empty.",
            status_code=422,
            code="provider_credential_invalid",
        )

    if normalized.startswith(LEGACY_PREFIXES):
        raise AppException(
            "Legacy credential format detected. Re-save or rotate this credential using the current encryption scheme.",
            status_code=422,
            code="legacy_credential_format",
        )

    if not normalized.startswith(FERNET_PREFIX):
        raise AppException(
            "Unsupported credential encryption format.",
            status_code=422,
            code="unsupported_credential_encryption_format",
        )

    token = normalized.removeprefix(FERNET_PREFIX).strip()
    if not token:
        raise AppException(
            "Encrypted credential payload is empty.",
            status_code=422,
            code="provider_credential_invalid",
        )

    cipher = _get_cipher()
    try:
        decrypted = cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise AppException(
            "Failed to decrypt provider credential.",
            status_code=422,
            code="provider_credential_decrypt_failed",
        ) from exc

    normalized_decrypted = decrypted.strip()
    if not normalized_decrypted:
        raise AppException(
            "Decrypted credential is empty.",
            status_code=422,
            code="provider_credential_invalid",
        )
    return normalized_decrypted


def mask_secret(raw_value: str) -> str:
    normalized = raw_value.strip()
    if not normalized:
        return "********"
    if len(normalized) <= 4:
        return "*" * len(normalized)
    if len(normalized) <= 8:
        return f"{normalized[0]}****{normalized[-1]}"
    return f"{normalized[:3]}****{normalized[-4:]}"


def _get_cipher() -> Fernet:
    settings = get_settings()
    key = (settings.credentials_encryption_key or "").strip()
    if not key:
        raise AppException(
            "CREDENTIALS_ENCRYPTION_KEY is not configured.",
            status_code=500,
            code="credentials_encryption_key_missing",
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise AppException(
            "CREDENTIALS_ENCRYPTION_KEY is invalid. It must be a valid Fernet key.",
            status_code=500,
            code="credentials_encryption_key_invalid",
        ) from exc
