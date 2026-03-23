from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AppException
from app.repositories.shared import TokenOwnedAutomationRecord, TokenOwnedPromptRecord
from app.services.external_catalog_service import ExternalCatalogService, ExternalCredentialRecord, ExternalProviderModelRecord, ExternalProviderRecord


class FakeSharedSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.automations_in_scope: dict[tuple[str, str], TokenOwnedAutomationRecord] = {}
        self.automations_unscoped: dict[str, TokenOwnedAutomationRecord] = {}
        self.prompts_in_scope: dict[tuple[str, str], TokenOwnedPromptRecord] = {}
        self.prompts_unscoped: dict[str, TokenOwnedPromptRecord] = {}

    @staticmethod
    def _ordered_slice(items: list, limit: int | None, offset: int | None):  # type: ignore[no-untyped-def]
        safe_offset = max(int(offset or 0), 0)
        if safe_offset:
            items = items[safe_offset:]
        if limit is not None:
            items = items[: max(int(limit), 0)]
        return items

    def list_automations_by_token(
        self,
        *,
        token_id,  # type: ignore[no-untyped-def]
        is_active=None,  # type: ignore[no-untyped-def]
        limit=None,  # type: ignore[no-untyped-def]
        offset=None,  # type: ignore[no-untyped-def]
    ):
        items = [item for (owner, _), item in self.automations_in_scope.items() if owner == str(token_id)]
        if is_active is not None:
            items = [item for item in items if bool(item.is_active) is bool(is_active)]
        items = sorted(items, key=lambda item: (item.name.lower(), str(item.id)))
        return self._ordered_slice(items, limit=limit, offset=offset)

    def get_automation_by_id_and_token(self, *, automation_id, token_id):  # type: ignore[no-untyped-def]
        return self.automations_in_scope.get((str(token_id), str(automation_id)))

    def get_automation_by_id(self, *, automation_id):  # type: ignore[no-untyped-def]
        return self.automations_unscoped.get(str(automation_id))

    def create_automation(self, *, token_id, name, provider_id, model_id, credential_id=None, output_type=None, result_parser=None, result_formatter=None, output_schema=None, is_active=True):  # type: ignore[no-untyped-def]
        item = TokenOwnedAutomationRecord(
            id=uuid4(),
            name=str(name),
            provider_id=provider_id,
            model_id=model_id,
            credential_id=credential_id,
            output_type=output_type,
            result_parser=result_parser,
            result_formatter=result_formatter,
            output_schema=output_schema,
            is_active=bool(is_active),
            owner_token_id=token_id,
        )
        self.automations_in_scope[(str(token_id), str(item.id))] = item
        self.automations_unscoped[str(item.id)] = item
        return item

    def update_automation(self, *, token_id, automation_id, changes=None):  # type: ignore[no-untyped-def]
        item = self.automations_in_scope.get((str(token_id), str(automation_id)))
        if item is None:
            return None
        payload = dict(changes or {})
        updated = TokenOwnedAutomationRecord(
            id=item.id,
            name=(str(payload["name"]) if "name" in payload else item.name),
            provider_id=(payload["provider_id"] if "provider_id" in payload else item.provider_id),
            model_id=(payload["model_id"] if "model_id" in payload else item.model_id),
            credential_id=(payload["credential_id"] if "credential_id" in payload else item.credential_id),
            output_type=(payload["output_type"] if "output_type" in payload else item.output_type),
            result_parser=(payload["result_parser"] if "result_parser" in payload else item.result_parser),
            result_formatter=(payload["result_formatter"] if "result_formatter" in payload else item.result_formatter),
            output_schema=(payload["output_schema"] if "output_schema" in payload else item.output_schema),
            is_active=(bool(payload["is_active"]) if "is_active" in payload else item.is_active),
            owner_token_id=item.owner_token_id,
        )
        self.automations_in_scope[(str(token_id), str(automation_id))] = updated
        self.automations_unscoped[str(automation_id)] = updated
        return updated

    def delete_automation_by_id_and_token(self, *, token_id, automation_id):  # type: ignore[no-untyped-def]
        removed = self.automations_in_scope.pop((str(token_id), str(automation_id)), None)
        if removed is None:
            return False
        self.automations_unscoped.pop(str(automation_id), None)
        return True

    def set_automation_status(self, *, token_id, automation_id, is_active):  # type: ignore[no-untyped-def]
        item = self.automations_in_scope.get((str(token_id), str(automation_id)))
        if item is None:
            return None
        updated = TokenOwnedAutomationRecord(
            id=item.id,
            name=item.name,
            provider_id=item.provider_id,
            model_id=item.model_id,
            credential_id=item.credential_id,
            output_type=item.output_type,
            result_parser=item.result_parser,
            result_formatter=item.result_formatter,
            output_schema=item.output_schema,
            is_active=bool(is_active),
            owner_token_id=item.owner_token_id,
        )
        self.automations_in_scope[(str(token_id), str(automation_id))] = updated
        self.automations_unscoped[str(automation_id)] = updated
        return updated

    def count_prompts_for_automation(self, *, token_id, automation_id):  # type: ignore[no-untyped-def]
        return len(
            [
                item
                for (owner, _), item in self.prompts_in_scope.items()
                if owner == str(token_id) and str(item.automation_id) == str(automation_id)
            ]
        )

    def list_prompts_by_token(
        self,
        *,
        token_id,  # type: ignore[no-untyped-def]
        automation_id=None,  # type: ignore[no-untyped-def]
        is_active=None,  # type: ignore[no-untyped-def]
        limit=None,  # type: ignore[no-untyped-def]
        offset=None,  # type: ignore[no-untyped-def]
    ):
        items = [item for (owner, _), item in self.prompts_in_scope.items() if owner == str(token_id)]
        if automation_id is not None:
            items = [item for item in items if str(item.automation_id) == str(automation_id)]
        if is_active is not None:
            items = [item for item in items if bool(item.is_active) is bool(is_active)]
        items = sorted(items, key=lambda item: (item.created_at, item.version), reverse=True)
        return self._ordered_slice(items, limit=limit, offset=offset)

    def get_prompt_by_id_and_token(self, *, prompt_id, token_id):  # type: ignore[no-untyped-def]
        return self.prompts_in_scope.get((str(token_id), str(prompt_id)))

    def get_prompt_by_id(self, *, prompt_id):  # type: ignore[no-untyped-def]
        return self.prompts_unscoped.get(str(prompt_id))

    def create_prompt(self, *, token_id, automation_id, prompt_text):  # type: ignore[no-untyped-def]
        prompt = TokenOwnedPromptRecord(
            id=uuid4(),
            automation_id=automation_id,
            prompt_text=str(prompt_text),
            version=1,
            created_at=datetime.now(timezone.utc),
            is_active=True,
            owner_token_id=token_id,
        )
        self.prompts_in_scope[(str(token_id), str(prompt.id))] = prompt
        self.prompts_unscoped[str(prompt.id)] = prompt
        return prompt

    def update_prompt(
        self,
        *,
        token_id,  # type: ignore[no-untyped-def]
        prompt_id,  # type: ignore[no-untyped-def]
        prompt_text=None,  # type: ignore[no-untyped-def]
        automation_id=None,  # type: ignore[no-untyped-def]
    ):
        item = self.prompts_in_scope.get((str(token_id), str(prompt_id)))
        if item is None:
            return None
        updated = TokenOwnedPromptRecord(
            id=item.id,
            automation_id=UUID(str(automation_id)) if automation_id is not None else item.automation_id,
            prompt_text=str(prompt_text) if prompt_text is not None else item.prompt_text,
            version=item.version,
            created_at=item.created_at,
            is_active=item.is_active,
            owner_token_id=item.owner_token_id,
        )
        self.prompts_in_scope[(str(token_id), str(prompt_id))] = updated
        self.prompts_unscoped[str(prompt_id)] = updated
        return updated

    def delete_prompt_by_id_and_token(self, *, token_id, prompt_id):  # type: ignore[no-untyped-def]
        removed = self.prompts_in_scope.pop((str(token_id), str(prompt_id)), None)
        if removed is None:
            return False
        self.prompts_unscoped.pop(str(prompt_id), None)
        return True

    def set_prompt_status(self, *, token_id, prompt_id, is_active):  # type: ignore[no-untyped-def]
        item = self.prompts_in_scope.get((str(token_id), str(prompt_id)))
        if item is None:
            return None
        updated = TokenOwnedPromptRecord(
            id=item.id,
            automation_id=item.automation_id,
            prompt_text=item.prompt_text,
            version=item.version,
            created_at=item.created_at,
            is_active=bool(is_active),
            owner_token_id=item.owner_token_id,
        )
        self.prompts_in_scope[(str(token_id), str(prompt_id))] = updated
        self.prompts_unscoped[str(prompt_id)] = updated
        return updated


class FakeProvider:
    def __init__(self, provider_id: UUID, *, is_active: bool = True) -> None:
        self.id = provider_id
        self.name = f"Provider-{provider_id.hex[:6]}"
        self.slug = f"provider-{provider_id.hex[:6]}"
        self.is_active = is_active


class FakeModel:
    def __init__(self, model_id: UUID, provider_id: UUID, *, is_active: bool = True) -> None:
        self.id = model_id
        self.provider_id = provider_id
        self.model_name = f"Model-{model_id.hex[:6]}"
        self.model_slug = f"model-{model_id.hex[:6]}"
        self.is_active = is_active


class FakeCredential:
    def __init__(self, credential_id: UUID, provider_id: UUID, *, is_active: bool = True) -> None:
        self.id = credential_id
        self.provider_id = provider_id
        self.credential_name = f"Cred-{credential_id.hex[:6]}"
        self.is_active = is_active


class FakeProviderRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, FakeProvider] = {}

    def get_by_id(self, provider_id: UUID):  # type: ignore[no-untyped-def]
        return self.items.get(provider_id)

    def list_all(self):  # type: ignore[no-untyped-def]
        return list(self.items.values())


class FakeModelRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, FakeModel] = {}

    def get_by_id(self, model_id: UUID):  # type: ignore[no-untyped-def]
        return self.items.get(model_id)

    def list_by_provider(self, provider_id: UUID):  # type: ignore[no-untyped-def]
        return [item for item in self.items.values() if item.provider_id == provider_id]


class FakeCredentialRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, FakeCredential] = {}

    def get_by_id(self, credential_id: UUID):  # type: ignore[no-untyped-def]
        return self.items.get(credential_id)

    def list_by_provider(self, provider_id: UUID):  # type: ignore[no-untyped-def]
        return [item for item in self.items.values() if item.provider_id == provider_id]


def _build_service() -> tuple[ExternalCatalogService, FakeCatalogRepository, FakeSharedSession]:
    session = FakeSharedSession()
    service = ExternalCatalogService(shared_session=session, operational_session=FakeSharedSession())  # type: ignore[arg-type]
    repository = FakeCatalogRepository()
    service.repository = repository  # type: ignore[assignment]
    service.providers = FakeProviderRepository()  # type: ignore[assignment]
    service.models = FakeModelRepository()  # type: ignore[assignment]
    service.credentials = FakeCredentialRepository()  # type: ignore[assignment]
    return service, repository, session


def _seed_automation(
    repository: FakeCatalogRepository,
    *,
    token_id: UUID,
    provider_id: UUID | None = None,
    model_id: UUID | None = None,
    credential_id: UUID | None = None,
    name: str = "Automation",
) -> TokenOwnedAutomationRecord:
    item = TokenOwnedAutomationRecord(
        id=uuid4(),
        name=name,
        provider_id=provider_id,
        model_id=model_id,
        credential_id=credential_id,
        output_type="text_output",
        result_parser="text_raw",
        result_formatter="text_plain",
        output_schema={"file_name_template": "execution_{execution_id}.txt"},
        is_active=True,
        owner_token_id=token_id,
    )
    repository.automations_in_scope[(str(token_id), str(item.id))] = item
    repository.automations_unscoped[str(item.id)] = item
    return item


def _seed_prompt(
    repository: FakeCatalogRepository,
    *,
    token_id: UUID,
    automation_id: UUID,
    prompt_text: str = "Prompt",
) -> TokenOwnedPromptRecord:
    item = TokenOwnedPromptRecord(
        id=uuid4(),
        automation_id=automation_id,
        prompt_text=prompt_text,
        version=1,
        created_at=datetime.now(timezone.utc),
        is_active=True,
        owner_token_id=token_id,
    )
    repository.prompts_in_scope[(str(token_id), str(item.id))] = item
    repository.prompts_unscoped[str(item.id)] = item
    return item


def _seed_operational_catalog(
    service: ExternalCatalogService,
    *,
    provider_active: bool = True,
    model_active: bool = True,
    credential_active: bool = True,
    with_credential: bool = True,
    model_provider_id: UUID | None = None,
    credential_provider_id: UUID | None = None,
) -> tuple[UUID, UUID, UUID | None]:
    provider_id = uuid4()
    model_id = uuid4()
    credential_id = uuid4() if with_credential else None

    assert isinstance(service.providers, FakeProviderRepository)
    assert isinstance(service.models, FakeModelRepository)
    assert isinstance(service.credentials, FakeCredentialRepository)

    service.providers.items[provider_id] = FakeProvider(provider_id, is_active=provider_active)
    service.models.items[model_id] = FakeModel(
        model_id,
        model_provider_id if model_provider_id is not None else provider_id,
        is_active=model_active,
    )
    if credential_id is not None:
        service.credentials.items[credential_id] = FakeCredential(
            credential_id,
            credential_provider_id if credential_provider_id is not None else provider_id,
            is_active=credential_active,
        )
    return provider_id, model_id, credential_id


def test_create_automation_binds_owner_from_authenticated_token() -> None:
    service, _, session = _build_service()
    token_id = uuid4()
    provider_id, model_id, _ = _seed_operational_catalog(service, with_credential=False)

    created = service.create_automation(
        token_id=token_id,
        name="Owner Bound",
        provider_id=provider_id,
        model_id=model_id,
        output_type=None,
        result_parser=None,
        result_formatter=None,
        output_schema={"file_name_template": "execution_{execution_id}.txt"},
    )

    assert created.owner_token_id == token_id
    assert created.provider_id == provider_id
    assert created.model_id == model_id
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_list_automations_returns_only_current_token_scope() -> None:
    service, repository, _ = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    _seed_automation(repository, token_id=token_a, name="A-1")
    _seed_automation(repository, token_id=token_b, name="B-1")

    items = service.list_automations(token_id=token_a, limit=100, offset=0)

    assert len(items) == 1
    assert items[0].owner_token_id == token_a


def test_get_automation_in_scope_returns_404_when_missing() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    automation_id = uuid4()

    with pytest.raises(AppException) as exc_info:
        service.get_automation_in_scope(token_id=token_id, automation_id=automation_id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.payload.code == "automation_not_found_in_scope"


def test_update_automation_in_scope_commits_changes() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id, name="Before")

    updated = service.update_automation(
        token_id=token_id,
        automation_id=automation.id,
        changes={"name": "After"},
    )

    assert updated.name == "After"
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_update_automation_out_of_scope_is_blocked() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation = _seed_automation(repository, token_id=token_b, name="B")

    with pytest.raises(AppException) as exc_info:
        service.update_automation(
            token_id=token_a,
            automation_id=automation.id,
            changes={"name": "X"},
        )

    assert exc_info.value.payload.code == "automation_not_found_in_scope"
    assert session.commit_calls == 0


def test_delete_automation_in_scope_succeeds() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)

    service.delete_automation(token_id=token_id, automation_id=automation.id)

    assert (str(token_id), str(automation.id)) not in repository.automations_in_scope
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_delete_automation_out_of_scope_is_blocked() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation = _seed_automation(repository, token_id=token_b)

    with pytest.raises(AppException) as exc_info:
        service.delete_automation(token_id=token_a, automation_id=automation.id)

    assert exc_info.value.payload.code == "automation_not_found_in_scope"
    assert session.commit_calls == 0


def test_delete_automation_with_prompt_dependency_is_blocked() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)
    _seed_prompt(repository, token_id=token_id, automation_id=automation.id)

    with pytest.raises(AppException) as exc_info:
        service.delete_automation(token_id=token_id, automation_id=automation.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.payload.code == "delete_blocked_by_dependencies"
    assert session.commit_calls == 0


def test_set_automation_status_in_scope() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)

    updated = service.set_automation_status(token_id=token_id, automation_id=automation.id, is_active=False)

    assert updated.is_active is False
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_create_prompt_only_inside_same_token_automation() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)

    created = service.create_prompt(
        token_id=token_id,
        automation_id=automation.id,
        prompt_text="Prompt in scope",
    )

    assert created.automation_id == automation.id
    assert created.owner_token_id == token_id
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_create_prompt_rejects_automation_from_other_token_scope() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation = _seed_automation(repository, token_id=token_b, name="Automation B")

    with pytest.raises(AppException) as exc_info:
        service.create_prompt(
            token_id=token_a,
            automation_id=automation.id,
            prompt_text="Prompt outside scope",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.payload.code == "automation_out_of_scope"
    assert session.commit_calls == 0


def test_list_prompts_returns_only_current_token_scope() -> None:
    service, repository, _ = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation_a = _seed_automation(repository, token_id=token_a, name="A")
    automation_b = _seed_automation(repository, token_id=token_b, name="B")
    _seed_prompt(repository, token_id=token_a, automation_id=automation_a.id, prompt_text="A prompt")
    _seed_prompt(repository, token_id=token_b, automation_id=automation_b.id, prompt_text="B prompt")

    items = service.list_prompts(token_id=token_a, limit=100, offset=0)

    assert len(items) == 1
    assert items[0].owner_token_id == token_a


def test_get_prompt_out_of_scope_is_blocked() -> None:
    service, repository, _ = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation_b = _seed_automation(repository, token_id=token_b, name="B")
    prompt = _seed_prompt(repository, token_id=token_b, automation_id=automation_b.id)

    with pytest.raises(AppException) as exc_info:
        service.get_prompt_in_scope(token_id=token_a, prompt_id=prompt.id)

    assert exc_info.value.payload.code == "prompt_not_found_in_scope"


def test_update_prompt_in_scope_succeeds() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)
    prompt = _seed_prompt(repository, token_id=token_id, automation_id=automation.id, prompt_text="Before")

    updated = service.update_prompt(token_id=token_id, prompt_id=prompt.id, prompt_text="After")

    assert updated.prompt_text == "After"
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_update_prompt_out_of_scope_is_blocked() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation_b = _seed_automation(repository, token_id=token_b, name="B")
    prompt = _seed_prompt(repository, token_id=token_b, automation_id=automation_b.id)

    with pytest.raises(AppException) as exc_info:
        service.update_prompt(token_id=token_a, prompt_id=prompt.id, prompt_text="X")

    assert exc_info.value.payload.code == "prompt_not_found_in_scope"
    assert session.commit_calls == 0


def test_update_prompt_automation_change_requires_new_automation_in_scope() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation_a = _seed_automation(repository, token_id=token_a, name="A")
    automation_b = _seed_automation(repository, token_id=token_b, name="B")
    prompt = _seed_prompt(repository, token_id=token_a, automation_id=automation_a.id)

    with pytest.raises(AppException) as exc_info:
        service.update_prompt(
            token_id=token_a,
            prompt_id=prompt.id,
            automation_id=automation_b.id,
        )

    assert exc_info.value.payload.code == "automation_not_found_in_scope"
    assert session.commit_calls == 0


def test_delete_prompt_in_scope_succeeds() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)
    prompt = _seed_prompt(repository, token_id=token_id, automation_id=automation.id)

    service.delete_prompt(token_id=token_id, prompt_id=prompt.id)

    assert (str(token_id), str(prompt.id)) not in repository.prompts_in_scope
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_delete_prompt_out_of_scope_is_blocked() -> None:
    service, repository, session = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation_b = _seed_automation(repository, token_id=token_b)
    prompt = _seed_prompt(repository, token_id=token_b, automation_id=automation_b.id)

    with pytest.raises(AppException) as exc_info:
        service.delete_prompt(token_id=token_a, prompt_id=prompt.id)

    assert exc_info.value.payload.code == "prompt_not_found_in_scope"
    assert session.commit_calls == 0


def test_set_prompt_status_in_scope() -> None:
    service, repository, session = _build_service()
    token_id = uuid4()
    automation = _seed_automation(repository, token_id=token_id)
    prompt = _seed_prompt(repository, token_id=token_id, automation_id=automation.id)

    updated = service.set_prompt_status(token_id=token_id, prompt_id=prompt.id, is_active=False)

    assert updated.is_active is False
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_list_prompts_with_automation_filter_requires_automation_in_scope() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    automation_id = uuid4()

    with pytest.raises(AppException) as exc_info:
        service.list_prompts(token_id=token_id, automation_id=automation_id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.payload.code == "automation_not_found_in_scope"


def test_create_automation_with_complete_runtime_configuration() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    provider_id, model_id, credential_id = _seed_operational_catalog(service, with_credential=True)

    created = service.create_automation(
        token_id=token_id,
        name="OCR Financeiro",
        provider_id=provider_id,
        model_id=model_id,
        credential_id=credential_id,
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={"columns": ["numero_processo", "categoria"]},
        is_active=True,
    )

    assert created.provider_id == provider_id
    assert created.model_id == model_id
    assert created.credential_id == credential_id
    assert created.output_type == "spreadsheet_output"
    assert created.result_parser == "tabular_structured"
    assert created.result_formatter == "spreadsheet_tabular"
    assert created.output_schema == {"columns": ["numero_processo", "categoria"]}
    assert created.owner_token_id == token_id


def test_create_automation_without_credential_is_allowed() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    provider_id, model_id, _ = _seed_operational_catalog(service, with_credential=False)

    created = service.create_automation(
        token_id=token_id,
        name="Sem Credencial",
        provider_id=provider_id,
        model_id=model_id,
        credential_id=None,
    )

    assert created.credential_id is None
    assert created.provider_id == provider_id
    assert created.model_id == model_id


def test_create_automation_rejects_invalid_provider() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    _, model_id, _ = _seed_operational_catalog(service, with_credential=False)

    with pytest.raises(AppException) as exc_info:
        service.create_automation(
            token_id=token_id,
            name="Invalid Provider",
            provider_id=uuid4(),
            model_id=model_id,
        )

    assert exc_info.value.payload.code == "provider_not_found"


def test_create_automation_rejects_invalid_model() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    provider_id, _, _ = _seed_operational_catalog(service, with_credential=False)

    with pytest.raises(AppException) as exc_info:
        service.create_automation(
            token_id=token_id,
            name="Invalid Model",
            provider_id=provider_id,
            model_id=uuid4(),
        )

    assert exc_info.value.payload.code == "provider_model_not_found"


def test_create_automation_rejects_model_provider_mismatch() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    foreign_provider_id = uuid4()
    provider_id, model_id, _ = _seed_operational_catalog(
        service,
        with_credential=False,
        model_provider_id=foreign_provider_id,
    )
    assert provider_id != foreign_provider_id

    with pytest.raises(AppException) as exc_info:
        service.create_automation(
            token_id=token_id,
            name="Model Mismatch",
            provider_id=provider_id,
            model_id=model_id,
        )

    assert exc_info.value.payload.code == "provider_model_mismatch"


def test_create_automation_rejects_credential_provider_mismatch() -> None:
    service, _, _ = _build_service()
    token_id = uuid4()
    foreign_provider_id = uuid4()
    provider_id, model_id, credential_id = _seed_operational_catalog(
        service,
        with_credential=True,
        credential_provider_id=foreign_provider_id,
    )
    assert credential_id is not None

    with pytest.raises(AppException) as exc_info:
        service.create_automation(
            token_id=token_id,
            name="Credential Mismatch",
            provider_id=provider_id,
            model_id=model_id,
            credential_id=credential_id,
        )

    assert exc_info.value.payload.code == "provider_credential_mismatch"


def test_update_automation_accepts_complete_runtime_changes() -> None:
    service, repository, _ = _build_service()
    token_id = uuid4()
    provider_a, model_a, credential_a = _seed_operational_catalog(service, with_credential=True)
    provider_b, model_b, credential_b = _seed_operational_catalog(service, with_credential=True)
    automation = _seed_automation(
        repository,
        token_id=token_id,
        provider_id=provider_a,
        model_id=model_a,
        credential_id=credential_a,
        name="Antes",
    )

    updated = service.update_automation(
        token_id=token_id,
        automation_id=automation.id,
        changes={
            "name": "Depois",
            "provider_id": provider_b,
            "model_id": model_b,
            "credential_id": credential_b,
            "output_type": "spreadsheet_output",
            "result_parser": "tabular_structured",
            "result_formatter": "spreadsheet_tabular",
            "output_schema": {"columns": ["coluna_a", "coluna_b"]},
            "is_active": False,
        },
    )

    assert updated.name == "Depois"
    assert updated.provider_id == provider_b
    assert updated.model_id == model_b
    assert updated.credential_id == credential_b
    assert updated.output_type == "spreadsheet_output"
    assert updated.result_parser == "tabular_structured"
    assert updated.result_formatter == "spreadsheet_tabular"
    assert updated.output_schema == {"columns": ["coluna_a", "coluna_b"]}
    assert updated.is_active is False


def test_get_automation_detail_returns_complete_configuration() -> None:
    service, repository, _ = _build_service()
    token_id = uuid4()
    provider_id, model_id, credential_id = _seed_operational_catalog(service, with_credential=True)
    automation = _seed_automation(
        repository,
        token_id=token_id,
        provider_id=provider_id,
        model_id=model_id,
        credential_id=credential_id,
        name="Detalhe",
    )

    detail = service.get_automation_in_scope(token_id=token_id, automation_id=automation.id)

    assert detail.provider_id == provider_id
    assert detail.model_id == model_id
    assert detail.credential_id == credential_id
    assert detail.output_schema == {"file_name_template": "execution_{execution_id}.txt"}


def test_list_external_providers_returns_safe_metadata() -> None:
    service, _, _ = _build_service()
    provider_id, _, _ = _seed_operational_catalog(service, with_credential=False)

    items = service.list_external_providers()

    assert isinstance(items, list)
    assert any(isinstance(item, ExternalProviderRecord) and item.id == provider_id for item in items)


def test_list_external_provider_models_returns_safe_metadata() -> None:
    service, _, _ = _build_service()
    provider_id, model_id, _ = _seed_operational_catalog(service, with_credential=False)

    items = service.list_external_provider_models(provider_id=provider_id)

    assert isinstance(items, list)
    assert any(isinstance(item, ExternalProviderModelRecord) and item.id == model_id for item in items)


def test_list_external_credentials_returns_safe_metadata() -> None:
    service, _, _ = _build_service()
    provider_id, _, credential_id = _seed_operational_catalog(service, with_credential=True)

    items = service.list_external_credentials(provider_id=provider_id)

    assert credential_id is not None
    assert isinstance(items, list)
    assert any(isinstance(item, ExternalCredentialRecord) and item.id == credential_id for item in items)
