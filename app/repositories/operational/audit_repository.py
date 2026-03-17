from sqlalchemy.orm import Session

from app.models.operational import DjangoAiAuditLog


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, audit_log: DjangoAiAuditLog) -> DjangoAiAuditLog:
        self.session.add(audit_log)
        self.session.flush()
        return audit_log
