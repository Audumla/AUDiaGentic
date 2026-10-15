"""Closed public projection for compact gateway evidence responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from audiagentic.components.agents.status.diagnostics_projection import (
    MAX_DIAGNOSTICS_BYTES,
    project_public_diagnostics,
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:256]


def _scalar(value: Any) -> Any:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _text(value)


def _observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    fields = (
        "schema_version", "event", "event_id", "event_seq", "attempt_epoch", "poll_seq",
        "observed_at", "producer_version", "build_version", "project_hash", "session_id",
        "request_id", "turn_id", "cdp_target_hash", "source", "previous_digest",
        "current_digest", "changed_fields", "causal_input_ids", "coalesced",
    )
    result = {
        field: (
            _scalar(value[field])
            if field not in {"changed_fields", "causal_input_ids", "coalesced"}
            else ([str(item)[:128] for item in value[field] if isinstance(item, str)][:32] if field in {"changed_fields", "causal_input_ids"} else {
                str(key): _scalar(item) for key, item in value[field].items() if str(key) in {"first_event_seq", "last_event_seq", "repeat_count", "first_poll_seq", "last_poll_seq", "max_gap_ms"}
            } if isinstance(value[field], Mapping) else {})
        )
        for field in fields
        if field in value
    }
    facts = value.get("facts")
    if isinstance(facts, Mapping):
        categories: dict[str, Any] = {}
        for category in ("dom-signals", "activity", "controls", "response-identity", "error-occurrence", "decision", "action"):
            raw = facts.get(category)
            if not isinstance(raw, Mapping):
                continue
            projected: dict[str, Any] = {}
            for key, item in raw.items():
                normalized = str(key).casefold().replace("_", "-")
                if normalized in {"text", "content", "body", "prompt", "response-text", "html", "value", "message"}:
                    continue
                if isinstance(item, (bool, int, float)):
                    projected[normalized] = item
                elif isinstance(item, str):
                    projected[normalized] = _text(item)
                elif isinstance(item, (list, tuple)):
                    projected[normalized] = [_text(raw_item) for raw_item in item if isinstance(raw_item, str)][:20]
                elif isinstance(item, Mapping):
                    projected[normalized] = {
                        str(nested_key)[:64]: (_scalar(nested_value) if not isinstance(nested_value, Mapping) else None)
                        for nested_key, nested_value in list(item.items())[:32]
                        if isinstance(nested_value, (bool, int, float, str))
                    }
            if projected:
                categories[category] = projected
        if categories:
            result["facts"] = categories
    return result


def _observation_summary(value: Any) -> dict[str, Any]:
    """Project summary metadata separately from a single observation event."""
    if not isinstance(value, Mapping):
        return {}
    result = {
        key: _scalar(value[key])
        for key in ("schema_version", "request_id", "count", "first_event_seq", "last_event_seq", "last_poll_seq", "has_more", "next_cursor")
        if key in value
    }
    latest = value.get("latest")
    if isinstance(latest, Mapping):
        result["latest"] = _observation(latest)
    return result


def _stream_page(value: Any, *, kind: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw_items = value.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    if kind == "observations":
        projected_items = [_observation(item) for item in items]
    elif kind == "recovery":
        allowed = {"schema-version", "event", "event-seq", "action-attempt-id", "action-kind", "attempt-epoch", "retry-budget", "submission-proven", "disposition", "outcome", "terminal", "causal-input-ids", "created-at", "binding"}
        projected_items = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            projected: dict[str, Any] = {}
            for key in allowed:
                if key not in item:
                    continue
                if key == "binding" and isinstance(item[key], Mapping):
                    projected[key] = {str(binding_key): _scalar(binding_value) for binding_key, binding_value in item[key].items() if str(binding_key) in {"project-id", "session-id", "chat-id", "turn-id"}}
                elif key == "causal-input-ids" and isinstance(item[key], (list, tuple)):
                    projected[key] = [str(raw)[:128] for raw in item[key] if isinstance(raw, str)][:32]
                else:
                    projected[key] = _scalar(item[key])
            projected_items.append(projected)
    else:
        projected_items = [
            {key: _scalar(item[key]) for key in ("event", "state", "timestamp") if key in item}
            for item in items if isinstance(item, Mapping)
        ]
    result = {key: value[key] for key in ("schema_version", "schema-version", "request_id", "request-id", "returned", "count", "has_more", "has-more", "next_cursor", "next-cursor") if key in value}
    result["items"] = projected_items
    return result


def project_public_gateway_evidence(payload: Mapping[str, Any], *, max_bytes: int = MAX_DIAGNOSTICS_BYTES) -> dict[str, Any]:
    """Route compact and opt-in evidence through one redaction/size boundary."""
    base = project_public_diagnostics(payload, max_bytes=max_bytes)
    reconnect = payload.get("reconnect-classification")
    reconnect_public = {
        key: (_scalar(reconnect[key]) if key != "read-only" else bool(reconnect[key]))
        for key in ("classification", "reason", "read-only", "provider-binding-present", "submission-proven")
        if isinstance(reconnect, Mapping) and key in reconnect
    }
    result: dict[str, Any] = {
        "schema_version": _text(payload.get("schema_version")) or "gateway-evidence.v1",
        "request-id": base.get("request-id"),
        "session-id": base.get("session-id"),
        "state": base.get("state"),
        "diagnostics": base.get("diagnostics"),
        "monitoring": base.get("monitoring"),
        "diagnostic-evidence": base.get("evidence", []),
        "observation-summary": _observation_summary(payload.get("observation-summary", {})),
        "latest-transition": base.get("latest-transition"),
        "reconnect-classification": reconnect_public,
    }
    for key, kind in (("observations", "observations"), ("recovery", "recovery"), ("history", "history")):
        page = _stream_page(payload.get(key), kind=kind)
        if page is not None:
            result[key] = page
    if base.get("truncated"):
        result["truncated"] = True

    def encoded_size() -> int:
        return len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    while encoded_size() > max_bytes:
        removed = False
        for key in ("observations", "recovery", "history"):
            page = result.get(key)
            if isinstance(page, dict) and page.get("items"):
                page["items"].pop(0)
                result["truncated"] = True
                removed = True
                break
        if not removed:
            result["diagnostic-evidence"] = []
            result["observation-summary"] = {}
            result["latest-transition"] = None
            result["truncated"] = True
            if encoded_size() > max_bytes:
                result["diagnostics"] = None
                result["monitoring"] = {}
            break
    return result


__all__ = ["project_public_gateway_evidence"]
