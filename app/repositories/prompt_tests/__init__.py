"""Persistence layer for prompt-test isolated entities."""

from app.repositories.prompt_tests.test_automation_repository import (
    PromptTestAutomationRepository,
    PromptTestAutomationRecord,
)

__all__ = [
    "PromptTestAutomationRepository",
    "PromptTestAutomationRecord",
]
