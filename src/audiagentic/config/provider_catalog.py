"""Provider model catalog helpers."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "provider-model-catalog.schema.json"


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def runtime_catalog_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers"


def runtime_catalog_path(project_root: Path, provider_id: str) -> Path:
    return runtime_catalog_root(project_root) / provider_id / "model-catalog.json"


def validate_model_catalog(payload: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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
        "fetched-at": fetched_at or _now_timestamp(),
        "source": source,
        "models": models,
    }
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="PRV-VALIDATION-005",
            kind="validation",
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
            code="PRV-IO-001",
            kind="io",
            message="failed to read provider model catalog",
            details={"provider-id": provider_id, "error": str(exc)},
        ) from exc
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="PRV-VALIDATION-006",
            kind="validation",
            message="provider model catalog failed validation",
            details={"issues": issues, "provider-id": provider_id},
        )
    return payload


def write_model_catalog(project_root: Path, payload: dict[str, Any]) -> Path:
    provider_id = payload.get("provider-id")
    if not provider_id:
        raise AudiaGenticError(
            code="PRV-VALIDATION-007",
            kind="validation",
            message="provider model catalog missing provider-id",
            details={},
        )
    issues = validate_model_catalog(payload)
    if issues:
        raise AudiaGenticError(
            code="PRV-VALIDATION-008",
            kind="validation",
            message="provider model catalog failed validation",
            details={"issues": issues, "provider-id": provider_id},
        )

    target_path = runtime_catalog_path(project_root, provider_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="model-catalog.", suffix=".tmp", dir=target_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return target_path


def catalog_model_ids(payload: dict[str, Any]) -> set[str]:
    return {model["model-id"] for model in payload.get("models", []) if "model-id" in model}


def catalog_is_stale(payload: dict[str, Any], *, max_age_hours: int, now_fn=None) -> bool:
    fetched_at = payload.get("fetched-at")
    if not fetched_at:
        return True
    now = datetime.fromisoformat((now_fn or _now_timestamp)().replace("Z", "+00:00"))
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    return (now - fetched).total_seconds() > max_age_hours * 3600
