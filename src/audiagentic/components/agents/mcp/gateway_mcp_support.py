"""Helpers shared by the gateway MCP servers (agent-facing and operator)."""

from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import (
    resolve_request_project_root,
    resolve_session_project_root,
)
from audiagentic.components.agents.gateway.evidence_projection import (
    public_gateway_scalar as _public_scalar,
)
from audiagentic.foundation.mcp.component_server import project_root_from_env

_RESPONSE_PREVIEW_FIELDS = frozenset({"output-preview", "output-truncated"})

_MAX_PAGE = 100


def _request_project_root(request_id: str):
    return resolve_request_project_root(project_root_from_env(), request_id)


def _session_project_root(session_id: str):
    return resolve_session_project_root(project_root_from_env(), session_id)


def _page_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGE:
        raise ValueError(f"limit must be an integer between 1 and {_MAX_PAGE}")
    return value

def _status_without_response_preview(status: dict[str, Any], *, include_response: bool = False) -> dict[str, Any]:
    """Keep MCP status compact and null-free; never spend tokens on a preview."""
    allowed = {"task_id", "request_id", "request-id", "session_id", "session-id", "lifecycle", "state", "activity_seq", "activity-seq", "activity_at", "activity-at", "activity", "activity_type", "outcome", "error_code", "error-code", "contract-version", "revision"}
    result = {key: _public_scalar(status.get(key)) for key in allowed if key not in _RESPONSE_PREVIEW_FIELDS and _public_scalar(status.get(key)) is not None}
    session_id = status.get("session_id") or status.get("session-id")
    if isinstance(session_id, str) and session_id:
        result["session_id"] = session_id
    if include_response and isinstance(status.get("response"), dict):
        response = status["response"]
        result["response"] = {
            key: _public_scalar(response.get(key))
            for key in ("text", "bytes", "format", "media_type")
            if _public_scalar(response.get(key)) is not None
        }
    return result


def _sparse(value: Any) -> Any:
    """Remove absent values from public MCP payloads without losing false/zero."""
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, raw in value.items():
            cleaned = _sparse(raw)
            if cleaned is None or cleaned == "" or cleaned == {} or cleaned == []:
                continue
            compact[key] = cleaned
        return compact
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _sparse(item)) is not None
            and cleaned != ""
            and cleaned != {}
            and cleaned != []
        ]
    return value
