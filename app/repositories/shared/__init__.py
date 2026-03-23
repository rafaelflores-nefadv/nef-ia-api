"""Shared repositories (tables owned by general system)."""

from app.repositories.shared.analysis_repository import SharedAnalysisRepository
from app.repositories.shared.automation_repository import (
    SharedAutomationRecord,
    SharedAutomationRepository,
    SharedAutomationRuntimeRecord,
    SharedAutomationTargetRecord,
)
from app.repositories.shared.execution_repository import SharedExecutionRepository
from app.repositories.shared.token_owned_catalog_repository import (
    TokenOwnedAutomationRecord,
    TokenOwnedCatalogRepository,
    TokenOwnedPromptRecord,
)

__all__ = [
    "SharedAutomationRepository",
    "SharedAutomationRecord",
    "SharedAutomationRuntimeRecord",
    "SharedAutomationTargetRecord",
    "SharedAnalysisRepository",
    "SharedExecutionRepository",
    "TokenOwnedCatalogRepository",
    "TokenOwnedAutomationRecord",
    "TokenOwnedPromptRecord",
]
