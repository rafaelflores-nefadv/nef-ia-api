from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.base import OperationalBase
from app.models import operational  # noqa: F401

settings = get_settings()
config = context.config

resolved_database_url = settings.resolved_database_url
if not isinstance(resolved_database_url, str) or not resolved_database_url.strip():
    raise RuntimeError("Database URL for Alembic must be a non-empty string.")

resolved_database_url = resolved_database_url.strip()
make_url(resolved_database_url)
config.set_main_option("sqlalchemy.url", resolved_database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = OperationalBase.metadata


def include_object(object_, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    if type_ == "table" and getattr(object_, "info", {}).get("skip_autogenerate"):
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
