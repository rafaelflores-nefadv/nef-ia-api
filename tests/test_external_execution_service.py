from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.repositories.operational.external_execution_context_repository import ExternalExecutionContextRecord
from app.repositories.shared import TokenOwnedAutomationRecord
from app.schemas.external_execution import ExternalExecutePromptRequest
from app.services.external_execution_service import ExternalExecutionService


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


@dataclass(slots=True)
class FakeAnalysisRequest:
    id: UUID
    automation_id: UUID


@dataclass(slots=True)
class FakeExecution:
    id: UUID
    analysis_request_id: UUID
    status: str
    created_at: datetime


@dataclass(slots=True)
class FakeQueueJob:
    id: UUID
    execution_id: UUID
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    updated_at: datetime


@dataclass(slots=True)
class FakeOutputFile:
    id: UUID
    execution_id: UUID
    file_type: str
    file_name: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    created_at: datetime


@dataclass(slots=True)
class FakeInputLink:
    execution_id: UUID
    request_file_id: UUID
    role: str
    order_index: int
    created_at: datetime


@dataclass(slots=True)
class FakeRequestFile:
    id: UUID
    file_name: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    created_at: datetime
    analysis_request_id: UUID


class FakeContexts:
    def __init__(self) -> None:
        self.items: dict[UUID, ExternalExecutionContextRecord] = {}

    def create(self, *, execution_id, token_id, analysis_request_id, resource_type, automation_id, prompt_id=None):  # type: ignore[no-untyped-def]
        now = datetime.now(timezone.utc)
        item = ExternalExecutionContextRecord(
            id=uuid4(),
            execution_id=execution_id,
            token_id=token_id,
            analysis_request_id=analysis_request_id,
            resource_type=resource_type,
            automation_id=automation_id,
            prompt_id=prompt_id,
            created_at=now,
            updated_at=now,
        )
        self.items[execution_id] = item
        return item

    def get_by_execution_id_and_scope(self, *, execution_id, token_id, resource_type=None):  # type: ignore[no-untyped-def]
        item = self.items.get(execution_id)
        if item is None or item.token_id != token_id:
            return None
        if resource_type is not None and item.resource_type != resource_type:
            return None
        return item

    def list_by_scope(self, *, token_id, resource_type=None, automation_id=None, prompt_id=None, limit=None, offset=None):  # type: ignore[no-untyped-def]
        rows = [item for item in self.items.values() if item.token_id == token_id]
        if resource_type is not None:
            rows = [item for item in rows if item.resource_type == resource_type]
        if automation_id is not None:
            rows = [item for item in rows if item.automation_id == automation_id]
        if prompt_id is not None:
            rows = [item for item in rows if item.prompt_id == prompt_id]
        rows = sorted(rows, key=lambda row: row.created_at, reverse=True)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows


def build_service(tmp_path: Path) -> tuple[ExternalExecutionService, dict]:
    ops = FakeSession()
    shared = FakeSession()
    service = ExternalExecutionService(operational_session=ops, shared_session=shared)  # type: ignore[arg-type]
    bag: dict = {}
    bag["contexts"] = FakeContexts()
    bag["queues"] = {}
    bag["shared_requests"] = {}
    bag["shared_executions"] = {}
    bag["output_files"] = {}
    bag["input_links"] = []
    bag["request_files"] = {}
    bag["downloads"] = {}

    service.contexts = bag["contexts"]  # type: ignore[assignment]
    service.queue_jobs = SimpleNamespace(get_latest_by_execution_id=lambda eid: bag["queues"].get(eid))  # type: ignore[assignment]
    service.shared_analysis = SimpleNamespace(
        create_request_for_automation=lambda automation_id: _create_request(bag, automation_id),
        get_request_by_id=lambda rid: bag["shared_requests"].get(rid),
    )  # type: ignore[assignment]
    service.shared_executions = SimpleNamespace(
        get_by_id=lambda eid: bag["shared_executions"].get(eid),
        list_by_ids=lambda ids: [bag["shared_executions"][iid] for iid in ids if iid in bag["shared_executions"]],
    )  # type: ignore[assignment]
    service.catalog = SimpleNamespace(
        get_automation_in_scope=lambda token_id, automation_id: _get_automation(bag, token_id, automation_id),
        get_prompt_in_scope=lambda token_id, prompt_id: (_raise_not_found("prompt_not_found_in_scope")),
    )  # type: ignore[assignment]
    service.execution_files = SimpleNamespace(
        get_by_id=lambda fid: bag["output_files"].get(fid),
        list_by_execution_id=lambda eid: [f for f in bag["output_files"].values() if f.execution_id == eid],
    )  # type: ignore[assignment]
    service.execution_inputs = SimpleNamespace(
        list_by_execution_id=lambda eid: [x for x in bag["input_links"] if x.execution_id == eid],
        list_by_request_file_id=lambda fid: [x for x in bag["input_links"] if x.request_file_id == fid],
    )  # type: ignore[assignment]
    service.request_files = SimpleNamespace(get_by_id=lambda fid: bag["request_files"].get(fid))  # type: ignore[assignment]
    service.file_service = SimpleNamespace(
        upload_request_file=lambda **_: SimpleNamespace(id=uuid4()),
        upload_request_json_payload=lambda **_: SimpleNamespace(id=uuid4()),
        get_execution_file_for_download=lambda file_id, token_permissions: bag["downloads"][file_id],  # type: ignore[arg-type]
        get_request_file_for_download=lambda file_id, token_permissions: bag["downloads"][file_id],  # type: ignore[arg-type]
    )  # type: ignore[assignment]
    service.execution_service = SimpleNamespace(create_execution=lambda **kwargs: _create_execution(bag, kwargs))  # type: ignore[assignment]
    return service, bag


def _create_request(bag: dict, automation_id: UUID) -> FakeAnalysisRequest:
    rid = uuid4()
    req = FakeAnalysisRequest(id=rid, automation_id=automation_id)
    bag["shared_requests"][rid] = req
    return req


def _create_execution(bag: dict, kwargs: dict) -> SimpleNamespace:
    eid = uuid4()
    qid = uuid4()
    now = datetime.now(timezone.utc)
    bag["shared_executions"][eid] = FakeExecution(
        id=eid,
        analysis_request_id=kwargs["analysis_request_id"],
        status=ExecutionStatus.QUEUED.value,
        created_at=now,
    )
    bag["queues"][eid] = FakeQueueJob(id=qid, execution_id=eid, started_at=None, finished_at=None, error_message=None, updated_at=now)
    return SimpleNamespace(execution_id=eid, queue_job_id=qid, status=ExecutionStatus.QUEUED)


def _get_automation(bag: dict, token_id: UUID, automation_id: UUID) -> TokenOwnedAutomationRecord:
    item = bag.get("automation")
    if item is None or item.id != automation_id or item.owner_token_id != token_id:
        raise AppException("Automation not found.", status_code=404, code="automation_not_found_in_scope")
    return item


def _raise_not_found(code: str):  # type: ignore[no-untyped-def]
    raise AppException("Not found.", status_code=404, code=code)


def test_execute_automation_json_creates_analysis_request(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_id = uuid4()
    automation_id = uuid4()
    bag["automation"] = TokenOwnedAutomationRecord(
        id=automation_id,
        name="A",
        provider_id=None,
        model_id=None,
        credential_id=None,
        output_type=None,
        result_parser=None,
        result_formatter=None,
        output_schema=None,
        is_active=True,
        owner_token_id=token_id,
    )

    result = service.execute_automation_in_scope(
        token_id=token_id,
        api_token=SimpleNamespace(id=token_id),  # type: ignore[arg-type]
        automation_id=automation_id,
        input_data={"payload": True},
        upload_files=None,
        ip_address=None,
        correlation_id=None,
    )

    assert result.execution_id in bag["shared_executions"]
    assert len(bag["shared_requests"]) == 1


def test_list_executions_respects_scope(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_a = uuid4()
    token_b = uuid4()
    now = datetime.now(timezone.utc)
    e1 = uuid4()
    e2 = uuid4()
    bag["contexts"].create(execution_id=e1, token_id=token_a, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["contexts"].create(execution_id=e2, token_id=token_b, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["shared_executions"][e1] = FakeExecution(id=e1, analysis_request_id=uuid4(), status="queued", created_at=now)
    bag["shared_executions"][e2] = FakeExecution(id=e2, analysis_request_id=uuid4(), status="queued", created_at=now)

    items = service.list_executions_in_scope(token_id=token_a, resource_type=None)
    assert len(items) == 1
    assert items[0].execution_id == e1


def test_execution_detail_flags(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_id = uuid4()
    eid = uuid4()
    now = datetime.now(timezone.utc)
    bag["contexts"].create(execution_id=eid, token_id=token_id, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["shared_executions"][eid] = FakeExecution(id=eid, analysis_request_id=uuid4(), status="completed", created_at=now)
    bag["output_files"][uuid4()] = FakeOutputFile(
        id=uuid4(), execution_id=eid, file_type="output", file_name="result.json", file_size=20, mime_type="application/json", checksum=None, created_at=now
    )

    detail = service.get_execution_in_scope(token_id=token_id, execution_id=eid, include_flags=True)
    assert detail.has_files is True
    assert detail.has_structured_result is True


def test_list_execution_files(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_id = uuid4()
    eid = uuid4()
    now = datetime.now(timezone.utc)
    bag["contexts"].create(execution_id=eid, token_id=token_id, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    out_id = uuid4()
    in_id = uuid4()
    bag["output_files"][out_id] = FakeOutputFile(
        id=out_id, execution_id=eid, file_type="output", file_name="result.txt", file_size=10, mime_type="text/plain", checksum=None, created_at=now
    )
    bag["request_files"][in_id] = FakeRequestFile(
        id=in_id, file_name="input.csv", file_size=5, mime_type="text/csv", checksum=None, created_at=now, analysis_request_id=uuid4()
    )
    bag["input_links"].append(FakeInputLink(execution_id=eid, request_file_id=in_id, role="primary", order_index=0, created_at=now))

    files = service.get_execution_files_in_scope(token_id=token_id, execution_id=eid)
    assert {f.file_id for f in files} == {out_id, in_id}


def test_file_out_of_scope_blocked(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_a = uuid4()
    token_b = uuid4()
    eid = uuid4()
    file_id = uuid4()
    bag["contexts"].create(execution_id=eid, token_id=token_b, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["output_files"][file_id] = FakeOutputFile(
        id=file_id, execution_id=eid, file_type="output", file_name="r.txt", file_size=1, mime_type="text/plain", checksum=None, created_at=datetime.now(timezone.utc)
    )
    with pytest.raises(AppException):
        service.get_file_in_scope(token_id=token_a, file_id=file_id)


def test_download_file_in_scope(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_id = uuid4()
    eid = uuid4()
    file_id = uuid4()
    bag["contexts"].create(execution_id=eid, token_id=token_id, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["output_files"][file_id] = FakeOutputFile(
        id=file_id, execution_id=eid, file_type="output", file_name="r.json", file_size=10, mime_type="application/json", checksum="x", created_at=datetime.now(timezone.utc)
    )
    p = tmp_path / "r.json"
    p.write_text('{\"ok\":true}', encoding="utf-8")
    bag["downloads"][file_id] = SimpleNamespace(absolute_path=str(p), file_name="r.json", mime_type="application/json", checksum="x")

    file_meta, downloadable = service.download_file_in_scope(
        token_id=token_id,
        token=SimpleNamespace(id=token_id),  # type: ignore[arg-type]
        file_id=file_id,
    )
    assert file_meta.file_id == file_id
    assert downloadable.file_name == "r.json"


def test_structured_result_json_and_empty(tmp_path: Path) -> None:
    service, bag = build_service(tmp_path)
    token_id = uuid4()
    eid = uuid4()
    file_id = uuid4()
    bag["contexts"].create(execution_id=eid, token_id=token_id, analysis_request_id=uuid4(), resource_type="automation", automation_id=uuid4())
    bag["output_files"][file_id] = FakeOutputFile(
        id=file_id, execution_id=eid, file_type="output", file_name="res.json", file_size=20, mime_type="application/json", checksum=None, created_at=datetime.now(timezone.utc)
    )
    pj = tmp_path / "res.json"
    pj.write_text('{\"items\":[1,2]}', encoding="utf-8")
    bag["downloads"][file_id] = SimpleNamespace(absolute_path=str(pj), file_name="res.json", mime_type="application/json", checksum=None)

    parsed = service.get_execution_structured_result_in_scope(
        token_id=token_id,
        token=SimpleNamespace(id=token_id),  # type: ignore[arg-type]
        execution_id=eid,
    )
    assert parsed.result == {"items": [1, 2]}

    bag["output_files"][file_id] = FakeOutputFile(
        id=file_id, execution_id=eid, file_type="output", file_name="res.xlsx", file_size=20, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", checksum=None, created_at=datetime.now(timezone.utc)
    )
    empty = service.get_execution_structured_result_in_scope(
        token_id=token_id,
        token=SimpleNamespace(id=token_id),  # type: ignore[arg-type]
        execution_id=eid,
    )
    assert empty.result is None


def test_payload_forbids_manual_owner() -> None:
    with pytest.raises(ValidationError):
        ExternalExecutePromptRequest.model_validate({"input_data": {"a": 1}, "owner_token_id": str(uuid4())})
