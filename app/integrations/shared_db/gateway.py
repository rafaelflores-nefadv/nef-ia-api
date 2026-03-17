from sqlalchemy.orm import Session


class SharedDatabaseGateway:
    """Abstraction for reads against general-system tables in shared PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self.session = session

