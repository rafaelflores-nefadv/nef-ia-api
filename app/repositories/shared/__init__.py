"""Shared repositories (tables owned by general system)."""

from app.repositories.shared.analysis_repository import SharedAnalysisRepository
from app.repositories.shared.automation_repository import SharedAutomationRepository, SharedAutomationRuntimeRecord
from app.repositories.shared.execution_repository import SharedExecutionRepository

__all__ = [
    "SharedAutomationRepository",
    "SharedAutomationRuntimeRecord",
    "SharedAnalysisRepository",
    "SharedExecutionRepository",
]
