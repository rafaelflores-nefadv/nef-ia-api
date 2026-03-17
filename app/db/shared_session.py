from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
shared_database_url = settings.resolved_shared_database_url

shared_engine = create_engine(
    shared_database_url,
    pool_pre_ping=True,
    echo=settings.sqlalchemy_echo,
)

SharedSessionLocal = sessionmaker(
    bind=shared_engine,
    autoflush=False,
    autocommit=False,
    class_=Session,
)


def get_shared_session() -> Generator[Session, None, None]:
    session = SharedSessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_shared_database() -> bool:
    with shared_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def dispose_shared_engine() -> None:
    shared_engine.dispose()
