from app.models.operational import DjangoAiAuditLog
from app.repositories.operational.audit_repository import AuditLogRepository


class AuditService:
    def __init__(self, repository: AuditLogRepository) -> None:
        self.repository = repository

    def register(self, event: DjangoAiAuditLog) -> DjangoAiAuditLog:
        return self.repository.add(event)
