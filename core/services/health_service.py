from __future__ import annotations

from typing import Any

from .api_client import FastAPIClient


def _status_meta(status: str) -> dict[str, str]:
    table = {
        "online": {"label": "Online", "css_class": "status-success"},
        "degraded": {"label": "Degradado", "css_class": "status-warning"},
        "offline": {"label": "Indisponivel", "css_class": "status-danger"},
    }
    return table.get(status, table["offline"])


def _normalize_check_label(name: str) -> str:
    mapping = {
        "database_operational": "Banco operacional",
        "database_shared": "Banco compartilhado",
        "redis": "Redis",
        "queue": "Fila",
        "provider_configured": "Provider configurado",
    }
    return mapping.get(name, name.replace("_", " ").title())


def _parse_live(client: FastAPIClient) -> dict[str, Any]:
    result = client.get_json("/health/live")

    if result.status_code is None:
        status = "offline"
        message = result.error or "Nao foi possivel consultar /health/live."
    elif not isinstance(result.data, dict):
        status = "degraded"
        message = result.error or "Resposta invalida em /health/live."
    elif str(result.data.get("status", "")).lower() == "ok":
        status = "online"
        message = "Endpoint /health/live respondeu com sucesso."
    else:
        status = "degraded"
        message = "Endpoint /health/live respondeu com status inesperado."

    meta = _status_meta(status)
    return {
        "status": status,
        "status_label": meta["label"],
        "status_css_class": meta["css_class"],
        "message": message,
        "http_status": result.status_code,
        "raw": result.data or {},
    }


def _parse_ready(client: FastAPIClient) -> dict[str, Any]:
    result = client.get_json("/health/ready")

    checks_payload = result.data.get("checks", {}) if isinstance(result.data, dict) else {}
    checks_payload = checks_payload if isinstance(checks_payload, dict) else {}

    checks = []
    degraded_count = 0
    for key, value in checks_payload.items():
        check_status = "online" if str(value).lower() == "ok" else "degraded"
        if check_status != "online":
            degraded_count += 1
        meta = _status_meta(check_status)
        checks.append(
            {
                "name": key,
                "label": _normalize_check_label(key),
                "status": check_status,
                "status_label": meta["label"],
                "status_css_class": meta["css_class"],
            }
        )

    if result.status_code is None:
        status = "offline"
        message = result.error or "Nao foi possivel consultar /health/ready."
    elif not isinstance(result.data, dict):
        status = "degraded"
        message = result.error or "Resposta invalida em /health/ready."
    else:
        payload_status = str(result.data.get("status", "")).lower()
        if payload_status == "ok" and degraded_count == 0:
            status = "online"
            message = "Readiness confirmada."
        elif payload_status in {"ok", "not_ready", "degraded"}:
            status = "degraded"
            message = "Readiness em estado degradado."
        else:
            status = "degraded"
            message = "Readiness com resposta inesperada."

    meta = _status_meta(status)
    return {
        "status": status,
        "status_label": meta["label"],
        "status_css_class": meta["css_class"],
        "message": message,
        "http_status": result.status_code,
        "checks": checks,
        "raw": result.data or {},
    }


def get_operational_health() -> dict[str, Any]:
    client = FastAPIClient()
    live = _parse_live(client)
    ready = _parse_ready(client)

    if live["status"] == "offline":
        overall_status = "offline"
    elif live["status"] == "online" and ready["status"] == "online":
        overall_status = "online"
    else:
        overall_status = "degraded"

    overall_meta = _status_meta(overall_status)

    environment_items = [
        {
            "service": "API FastAPI",
            "status": live["status"],
            "status_label": live["status_label"],
            "status_css_class": live["status_css_class"],
            "detail": live["message"],
        },
        {
            "service": "Readiness geral",
            "status": ready["status"],
            "status_label": ready["status_label"],
            "status_css_class": ready["status_css_class"],
            "detail": ready["message"],
        },
    ]
    environment_items.extend(
        {
            "service": check["label"],
            "status": check["status"],
            "status_label": check["status_label"],
            "status_css_class": check["status_css_class"],
            "detail": "",
        }
        for check in ready["checks"]
    )

    errors = []
    if live["status"] == "offline":
        errors.append(live["message"])
    if ready["status"] == "offline":
        errors.append(ready["message"])

    return {
        "live": live,
        "ready": ready,
        "overall": {
            "status": overall_status,
            "status_label": overall_meta["label"],
            "status_css_class": overall_meta["css_class"],
        },
        "environment_items": environment_items,
        "errors": errors,
    }
