"""Durable interaction request storage."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.interaction.models import AskResponse, DEFAULT_TTL_SECONDS, ResponseStatus
from audiagentic.foundation.paths.names import project_marker_path

logger = logging.getLogger(__name__)


def interactions_root(project_root: Path) -> Path:
    return project_marker_path(project_root) / "runtime" / "interactions"


def interaction_path(project_root: Path, request_id: str) -> Path:
    return interactions_root(project_root) / f"{request_id}.json"


def _validate_record(payload: dict[str, Any]) -> None:
    from audiagentic.foundation.contracts.schema_registry import validate_with_schema

    issues = validate_with_schema("interaction-request", payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-INTERACT-001",
            kind="interaction",
            message="interaction request failed validation",
            details={"issues": issues},
        )


def read_record(project_root: Path, request_id: str) -> dict[str, Any]:
    path = interaction_path(project_root, request_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-INTERACT-001",
            kind="interaction",
            message="failed to read interaction request",
            details={"request-id": request_id, "error": str(exc)},
        ) from exc
    _validate_record(payload)
    return payload


def write_record(project_root: Path, payload: dict[str, Any]) -> None:
    _validate_record(payload)
    atomic_write_json(interaction_path(project_root, payload["request_id"]), payload)


def _is_expired(payload: dict[str, Any], now_ts: str) -> bool:
    if payload.get("state") != "pending":
        return False
    requested_at = str(payload.get("requested_at", ""))
    ttl_seconds = int(payload.get("ttl_seconds") or DEFAULT_TTL_SECONDS)
    requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    expires = requested + timedelta(seconds=ttl_seconds)
    now = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
    return expires <= now
