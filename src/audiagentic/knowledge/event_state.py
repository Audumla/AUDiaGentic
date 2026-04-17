"""Event state I/O, fingerprinting, and validation utilities.

Handles persistent state for event processing: loaded/saved event IDs, source
fingerprints, journal maintenance, and payload filter validation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import KnowledgeConfig
from .utils import dump_yaml, load_yaml_file, now_utc


def load_event_adapters(config: KnowledgeConfig) -> list[dict[str, Any]]:
    """Load event adapters from config file."""
    data = load_yaml_file(config.event_adapter_file, {})
    adapters = data.get("adapters", []) if isinstance(data, dict) else []
    return [item for item in adapters if isinstance(item, dict)]


def load_event_state(config: KnowledgeConfig) -> dict[str, Any]:
    """Load event processing state (processed IDs and source fingerprints)."""
    data = load_yaml_file(config.event_state_file, {"sources": {}, "processed_event_ids": []})
    if not isinstance(data, dict):
        return {"sources": {}, "processed_event_ids": []}
    data.setdefault("sources", {})
    data.setdefault("processed_event_ids", [])
    return data


def save_event_state(config: KnowledgeConfig, state: dict[str, Any]) -> None:
    """Save event processing state to disk, pruning if necessary."""
    max_events = config.raw.get("events", {}).get("max_processed_events", 1000)
    if "processed_event_ids" in state and len(state["processed_event_ids"]) > max_events:
        state["processed_event_ids"] = state["processed_event_ids"][-max_events:]
    config.event_state_file.parent.mkdir(parents=True, exist_ok=True)
    config.event_state_file.write_text(dump_yaml(state), encoding="utf-8")


def prune_event_state(config: KnowledgeConfig, max_events: int | None = None) -> dict[str, Any]:
    """Prune old processed event IDs and journal entries."""
    if max_events is None:
        max_events = config.raw.get("events", {}).get("max_processed_events", 1000)
    state = load_event_state(config)
    original_count = len(state.get("processed_event_ids", []))
    pruned_count = 0
    if original_count > max_events:
        state["processed_event_ids"] = state["processed_event_ids"][-max_events:]
        pruned_count = original_count - max_events
        save_event_state(config, state)
    journal_pruned = _prune_event_journal(config, max_events)
    return {
        "ok": True,
        "pruned": pruned_count + journal_pruned,
        "pruned_state": pruned_count,
        "pruned_journal": journal_pruned,
        "remaining": len(state["processed_event_ids"]),
        "max_events": max_events,
    }


def _prune_event_journal(config: KnowledgeConfig, max_events: int) -> int:
    """Prune old entries from event journal file."""
    journal = config.event_journal_file
    if not journal.exists():
        return 0
    lines = journal.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_events:
        return 0
    pruned = len(lines) - max_events
    journal.write_text("\n".join(lines[-max_events:]), encoding="utf-8")
    return pruned


def _append_event_journal(config: KnowledgeConfig, event: Any) -> None:
    """Append processed event to journal file."""
    config.event_journal_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "event_id": event.event_id,
        "adapter_id": event.adapter_id,
        "event_name": event.event_name,
        "source_path": event.source_path,
        "status": event.status,
        "observed_at": event.observed_at,
        "affected_pages": event.affected_pages,
        "summary": event.summary,
        "details": event.details,
    }
    with config.event_journal_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _record_event_source(
    state: dict[str, Any], source_path: Any, event: Any, adapter: dict[str, Any]
) -> None:
    """Record source state after processing an event."""
    from .diffing import normalize_text

    source_kind = _adapter_source_kind(adapter)
    if source_kind == "event_stream":
        state.setdefault("sources", {})[event.source_path] = _event_stream_source_state(
            adapter, source_path
        )
        return
    state.setdefault("sources", {})[event.source_path] = {
        "adapter_id": event.adapter_id,
        "source_kind": source_kind,
        "fingerprint": event.fingerprint_now,
        "observed_at": event.observed_at,
        "snapshot_text": normalize_text(
            source_path, source_path.read_text(encoding="utf-8", errors="replace")
        ),
    }


def _event_stream_source_state(adapter: dict[str, Any], source_path: Any) -> dict[str, Any]:
    """Get current source state for an event stream."""
    from .diffing import normalize_text

    current_text = normalize_text(
        source_path, source_path.read_text(encoding="utf-8", errors="replace")
    )
    return {
        "adapter_id": str(adapter.get("id", "unknown")),
        "source_kind": "event_stream",
        "fingerprint": _fingerprint_text(current_text),
        "observed_at": now_utc().isoformat(),
        "snapshot_text": current_text,
    }


def _fingerprint_text(text: str) -> str:
    """Hash text content to detect changes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _adapter_source_kind(adapter: dict[str, Any]) -> str:
    """Get source kind from adapter config (file_change or event_stream)."""
    return str(adapter.get("source_kind", "file_change")).strip() or "file_change"


def _adapter_by_id(config: KnowledgeConfig, adapter_id: str) -> dict[str, Any] | None:
    """Look up adapter by ID."""
    for adapter in load_event_adapters(config):
        if str(adapter.get("id")) == adapter_id:
            return adapter
    return None


def _event_id(adapter: dict[str, Any], rel_path: str, fingerprint: str) -> str:
    """Generate unique event ID for file change."""
    return f"{adapter.get('id', 'adapter')}::{rel_path}::{fingerprint[:16]}"


def _stream_event_id(adapter: dict[str, Any], rel_path: str, raw: dict[str, Any]) -> str:
    """Generate unique event ID for event stream entry."""
    explicit = raw.get("event_id")
    if explicit:
        return str(explicit)
    material = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{adapter.get('id', 'adapter')}::{rel_path}::stream::{digest}"


def _lookup_dotted(data: Any, dotted: str) -> Any:
    """Navigate nested dict using dotted path (e.g., 'payload.status')."""
    current = data
    for segment in [seg for seg in dotted.split(".") if seg]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _matches_payload_filters(raw: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Check if event payload matches configured filters."""
    equals = filters.get("equals", {}) if isinstance(filters.get("equals"), dict) else {}
    includes = filters.get("in", {}) if isinstance(filters.get("in"), dict) else {}
    contains_any = (
        filters.get("contains_any", {}) if isinstance(filters.get("contains_any"), dict) else {}
    )
    for dotted, expected in equals.items():
        if _lookup_dotted(raw, str(dotted)) != expected:
            return False
    for dotted, options in includes.items():
        value = _lookup_dotted(raw, str(dotted))
        if isinstance(options, list):
            allowed = [str(x) for x in options]
        else:
            allowed = [str(options)]
        if str(value) not in allowed:
            return False
    for dotted, options in contains_any.items():
        value = _lookup_dotted(raw, str(dotted))
        haystack = "" if value is None else str(value)

        tokens = [str(x) for x in (options if isinstance(options, list) else [options])]
        if not any(token in haystack for token in tokens if token):
            return False
    return True
