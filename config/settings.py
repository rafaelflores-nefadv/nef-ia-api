import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


_load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS: list[str] = _env_list("DJANGO_ALLOWED_HOSTS", ["*"])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "providers",
    "models_catalog",
    "prompts",
    "test_automations",
    "test_prompts",
    "credentials",
    "operations",
    "executions",
    "files_admin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DJANGO_DB_ENGINE = os.getenv("DJANGO_DB_ENGINE", "django.db.backends.postgresql").strip()

DATABASES = {
    "default": {
        "ENGINE": DJANGO_DB_ENGINE or "django.db.backends.postgresql",
        "NAME": os.getenv("DJANGO_DB_NAME", "nef_ia_django"),
        "USER": os.getenv("DJANGO_DB_USER", "postgres"),
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DJANGO_DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DJANGO_DB_PORT", "5432"),
    }
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    sslmode = os.getenv("DJANGO_DB_SSLMODE", "").strip()
    if sslmode:
        DATABASES["default"]["OPTIONS"] = {"sslmode": sslmode}
elif DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"]["OPTIONS"] = {
        "charset": os.getenv("DJANGO_DB_CHARSET", "utf8mb4"),
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "pt-br")
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "America/Cuiaba")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000")
FASTAPI_TIMEOUT_SECONDS = float(os.getenv("FASTAPI_TIMEOUT_SECONDS", "2.5"))
FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS = float(
    os.getenv("FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS", str(FASTAPI_TIMEOUT_SECONDS))
)
FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS = float(
    os.getenv("FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS", "240")
)
FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS = float(
    os.getenv("FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS", "60")
)
FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS = float(
    os.getenv("FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS", "30")
)
FASTAPI_ADMIN_TOKEN = os.getenv("FASTAPI_ADMIN_TOKEN", "")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
