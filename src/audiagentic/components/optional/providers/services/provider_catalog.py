"""Provider model catalog helpers."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z


def runtime_catalog_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers"


def runtime_catalog_path(project_root: Path, provider_id: str) -> Path:
    return runtime_catalog_root(project_root) / provider_id / "model-catalog.json"


def validate_model_catalog(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("provider-model-catalog")
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(payload))


def build_model_catalog(
    *,
    provider_id: str,
    models: list[dict[str, Any]],
    fetched_at: str | None = None,
    source: str = "cli",
) -> dict[str, Any]:
    payload = {
        "contract-version": "v1",
        "provider-id": provider_id,
        "fetched-at": fetched_at or now_iso_z(),
        "source": source,
        "models": models,
    }
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCAT-001",
            kind="providers",
            message="provider model catalog failed validation",
            details={"issues": issues, "provider-id": provider_id},
        )
    return payload


def read_model_catalog(project_root: Path, provider_id: str) -> dict[str, Any]:
    path = runtime_catalog_path(project_root, provider_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-PCAT-001",
            kind="providers",
            message="failed to read provider model catalog",
            details={"provider-id": provider_id, "error": str(exc)},
        ) from exc
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCAT-002",
            kind="providers",
            message="provider model catalog failed validation",
            details={"issues": issues, "provider-id": provider_id},
        )
    return payload


def write_model_catalog(project_root: Path, payload: dict[str, Any]) -> Path:
    provider_id = payload.get("provider-id")
    if not provider_id:
        raise AudiaGenticError(
            code="VAL-PCAT-003",
            kind="providers",
            message="provider model catalog missing provider-id",
            details={},
        )
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCAT-004",
            kind="providers",
            message="provider model catalog failed validation",
            details={"issues": issues, "provider-id": provider_id},
        )

    target_path = runtime_catalog_path(project_root, provider_id)
    atomic_write_json(target_path, payload)
    return target_path


def catalog_model_ids(payload: dict[str, Any]) -> set[str]:
    return {model["model-id"] for model in payload.get("models", []) if "model-id" in model}


def catalog_is_stale(payload: dict[str, Any], *, max_age_hours: int, now_fn=None) -> bool:
    fetched_at = payload.get("fetched-at")
    if not fetched_at:
        return True
    now = datetime.fromisoformat((now_fn or now_iso_z)().replace("Z", "+00:00"))
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    return (now - fetched).total_seconds() > max_age_hours * 3600
