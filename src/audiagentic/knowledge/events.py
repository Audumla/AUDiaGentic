from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# Standard: standard-0013 (Event subscription configuration standard)
# Protocol: spec-0055 (Interoperability event layer specification)
from .config import KnowledgeConfig, load_config
from .diffing import normalize_text, summarize_structured_change, unified_diff_excerpt
from .hooks import evaluate_source
from .models import EventRecord
from .registry import load_event_action_registry, resolve_registry_handler
from .sync import mark_pages_stale
from .utils import dump_yaml, load_yaml_file, now_utc

DEFAULT_PLANNING_AFFECTED_PAGES = [
    "system-planning",
    "system-knowledge",
    "guide-using-planning",
    "tool-cli",
    "tool-mcp",
    "pattern-event-bridge",
    "pattern-page-lifecycle",
]


def load_event_adapters(config: KnowledgeConfig) -> list[dict[str, Any]]:
    data = load_yaml_file(config.event_adapter_file, {})
    adapters = data.get("adapters", []) if isinstance(data, dict) else []
    return [item for item in adapters if isinstance(item, dict)]


def load_event_state(config: KnowledgeConfig) -> dict[str, Any]:
    data = load_yaml_file(config.event_state_file, {"sources": {}, "processed_event_ids": []})
    if not isinstance(data, dict):
        return {"sources": {}, "processed_event_ids": []}
    data.setdefault("sources", {})
    data.setdefault("processed_event_ids", [])
    return data


def save_event_state(config: KnowledgeConfig, state: dict[str, Any]) -> None:
    max_events = config.raw.get("events", {}).get("max_processed_events", 1000)
    if "processed_event_ids" in state and len(state["processed_event_ids"]) > max_events:
        state["processed_event_ids"] = state["processed_event_ids"][-max_events:]
    config.event_state_file.parent.mkdir(parents=True, exist_ok=True)
    config.event_state_file.write_text(dump_yaml(state), encoding="utf-8")


def prune_event_state(config: KnowledgeConfig, max_events: int | None = None) -> dict[str, Any]:
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
    journal = config.event_journal_file
    if not journal.exists():
        return 0
    lines = journal.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_events:
        return 0
    pruned = len(lines) - max_events
    journal.write_text("\n".join(lines[-max_events:]), encoding="utf-8")
    return pruned


def record_event_baseline(config: KnowledgeConfig) -> dict[str, Any]:
    state = load_event_state(config)
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    for adapter in load_event_adapters(config):
        source_kind = _adapter_source_kind(adapter)
        for rel_path in _resolve_relative_paths(config, adapter):
            abs_path = config.root / rel_path
            if not abs_path.exists():
                continue
            if source_kind == "event_stream":
                for raw in _iter_event_stream_entries(abs_path, adapter):
                    processed.add(_stream_event_id(adapter, rel_path, raw))
                state.setdefault("sources", {})[rel_path] = _event_stream_source_state(
                    adapter, abs_path
                )
                continue
            current_text = normalize_text(
                abs_path, abs_path.read_text(encoding="utf-8", errors="replace")
            )
            state.setdefault("sources", {})[rel_path] = {
                "adapter_id": str(adapter.get("id", "unknown")),
                "source_kind": source_kind,
                "fingerprint": _fingerprint_text(current_text),
                "observed_at": now_utc().isoformat(),
                "snapshot_text": current_text,
            }
    state["processed_event_ids"] = sorted(processed)
    save_event_state(config, state)
    return state


def scan_events(config: KnowledgeConfig) -> list[EventRecord]:
    adapters = load_event_adapters(config)
    state = load_event_state(config)
    events: list[EventRecord] = []
    for adapter in adapters:
        source_kind = _adapter_source_kind(adapter)
        if source_kind == "event_stream":
            events.extend(_scan_event_stream_adapter(config, adapter, state))
        else:
            events.extend(_scan_file_change_adapter(config, adapter, state))
    return events


def load_event_handlers(config: KnowledgeConfig) -> dict[str, Any]:
    """Load event handlers configuration."""
    handlers_file = config.handlers_file
    if not handlers_file.exists():
        return {"default_handler": "deterministic", "handlers": []}
    data = load_yaml_file(handlers_file, {})
    if not isinstance(data, dict):
        return {"default_handler": "deterministic", "handlers": []}
    return data


def process_events(
    config: KnowledgeConfig, events: list[EventRecord] | None = None
) -> dict[str, Any]:
    state = load_event_state(config)
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    events = events or scan_events(config)
    action_registry = load_event_action_registry(config)
    handlers_config = load_event_handlers(config)
    auto_apply = config.auto_apply_proposals
    auto_mark_stale = config.auto_mark_stale
    context: dict[str, Any] = {
        "generated_proposals": [],
        "marked_stale_pages": set(),
        "handled": [],
        "page_event_map": {},
        "applied_proposals": [],
    }
    for event in events:
        if event.event_id in processed:
            continue
        adapter = _adapter_by_id(config, event.adapter_id)
        if not adapter:
            continue
        path_evals = evaluate_source(config, event.source_path)
        if path_evals and not any(item.get("eligible") for item in path_evals):
            continue
        handler_config = _match_event_handler(event, handlers_config)
        action_name = str(
            handler_config.get("action", adapter.get("action", "generate_sync_proposal"))
        )
        handler, defaults = resolve_registry_handler(action_registry, action_name)
        hook_action_args = {}
        if path_evals:
            for eval_result in path_evals:
                if eval_result.get("eligible") and eval_result.get("action_args"):
                    hook_action_args = {**hook_action_args, **eval_result.get("action_args", {})}
        runtime_action = {
            **defaults,
            **handler_config.get("action_args", {}),
            **adapter.get("action_args", {}),
            **hook_action_args,
        }
        handler(
            config=config,
            event=event,
            adapter=adapter,
            state=state,
            context=context,
            action_args=runtime_action,
        )
        _record_event_source(state, config.root / event.source_path, event, adapter)
        _append_event_journal(config, event)
        context["handled"].append(event.event_id)
    if auto_mark_stale and context["marked_stale_pages"]:
        mark_pages_stale(config, sorted(context["marked_stale_pages"]))
    if auto_apply and context["generated_proposals"]:
        from .sync import apply_all_proposals

        proposal_paths = [config.root / p for p in context["generated_proposals"]]
        apply_results = apply_all_proposals(config, proposal_paths)
        context["applied_proposals"] = apply_results
    save_event_state(
        config, {**state, "processed_event_ids": sorted(processed | set(context["handled"]))}
    )
    return {
        "processed_event_ids": list(context["handled"]),
        "marked_stale_pages": sorted(context["marked_stale_pages"]),
        "generated_proposals": context["generated_proposals"],
        "applied_proposals": context["applied_proposals"],
    }


def _match_event_handler(event: EventRecord, handlers_config: dict[str, Any]) -> dict[str, Any]:
    """Match an event to a handler configuration."""
    handlers = handlers_config.get("handlers", [])
    default_handler = handlers_config.get("default_handler", "deterministic")
    for handler in handlers:
        patterns = handler.get("event_patterns", [])
        if patterns and not any(fnmatch(event.event_name, pattern) for pattern in patterns):
            continue
        filters = handler.get("payload_filters", {})
        if filters:
            raw_event = event.details.get("raw_event", event.details.get("payload", {}))
            if not _matches_payload_filters(raw_event, filters):
                continue
        return handler
    return {"handler": default_handler, "action": "generate_sync_proposal", "action_args": {}}


def action_generate_sync_proposal(
    *,
    config: KnowledgeConfig,
    event: EventRecord,
    adapter: dict[str, Any],
    state: dict[str, Any],
    context: dict[str, Any],
    action_args: dict[str, Any],
) -> None:
    for page_id in event.affected_pages:
        context["page_event_map"].setdefault(page_id, []).append(event)
    for page_id in event.affected_pages:
        proposal_path = _write_event_proposal(
            config,
            page_id,
            context["page_event_map"][page_id],
            mode=str(action_args.get("proposal_mode", config.proposal_default_mode)),
        )
        rel = str(proposal_path.relative_to(config.root))
        if rel not in context["generated_proposals"]:
            context["generated_proposals"].append(rel)


def action_mark_stale(
    *,
    config: KnowledgeConfig,
    event: EventRecord,
    adapter: dict[str, Any],
    state: dict[str, Any],
    context: dict[str, Any],
    action_args: dict[str, Any],
) -> None:
    context["marked_stale_pages"].update(event.affected_pages)


def action_mark_stale_and_generate_sync_proposal(
    *,
    config: KnowledgeConfig,
    event: EventRecord,
    adapter: dict[str, Any],
    state: dict[str, Any],
    context: dict[str, Any],
    action_args: dict[str, Any],
) -> None:
    action_mark_stale(
        config=config,
        event=event,
        adapter=adapter,
        state=state,
        context=context,
        action_args=action_args,
    )
    action_generate_sync_proposal(
        config=config,
        event=event,
        adapter=adapter,
        state=state,
        context=context,
        action_args=action_args,
    )


def action_ignore(
    *,
    config: KnowledgeConfig,
    event: EventRecord,
    adapter: dict[str, Any],
    state: dict[str, Any],
    context: dict[str, Any],
    action_args: dict[str, Any],
) -> None:
    return None


def _scan_file_change_adapter(
    config: KnowledgeConfig, adapter: dict[str, Any], state: dict[str, Any]
) -> list[EventRecord]:
    events: list[EventRecord] = []
    for rel_path in _resolve_relative_paths(config, adapter):
        abs_path = config.root / rel_path
        old = state["sources"].get(rel_path)
        if not abs_path.exists():
            continue
        current_text = normalize_text(
            abs_path, abs_path.read_text(encoding="utf-8", errors="replace")
        )
        current_fingerprint = _fingerprint_text(current_text)
        old_text = old.get("snapshot_text") if isinstance(old, dict) else None
        old_fingerprint = old.get("fingerprint") if isinstance(old, dict) else None
        if old_fingerprint == current_fingerprint:
            continue
        details = summarize_structured_change(abs_path, old_text, current_text)
        event_id = _event_id(adapter, rel_path, current_fingerprint)
        events.append(
            EventRecord(
                event_id=event_id,
                adapter_id=str(adapter.get("id", "unknown")),
                event_name=str(adapter.get("event_name", "knowledge.source.changed")),
                source_path=rel_path,
                status="changed" if old_fingerprint else "discovered",
                observed_at=now_utc().isoformat(),
                affected_pages=[str(x) for x in adapter.get("affects_pages", []) or []],
                fingerprint_before=old_fingerprint,
                fingerprint_now=current_fingerprint,
                summary=_build_summary(adapter, rel_path, details),
                diff_excerpt=unified_diff_excerpt(
                    old_text,
                    current_text,
                    rel_path,
                    config.diff_context_lines,
                    config.diff_max_lines,
                ),
                details=details,
            )
        )
    return events


def _scan_event_stream_adapter(
    config: KnowledgeConfig, adapter: dict[str, Any], state: dict[str, Any]
) -> list[EventRecord]:
    events: list[EventRecord] = []
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    patterns = [str(x) for x in adapter.get("event_name_patterns", []) or []]
    filters = (
        adapter.get("payload_filters", {})
        if isinstance(adapter.get("payload_filters"), dict)
        else {}
    )
    status_field = str(adapter.get("status_field", "payload.status"))
    summary_fields = [str(x) for x in adapter.get("summary_fields", []) or []]
    for rel_path in _resolve_relative_paths(config, adapter):
        abs_path = config.root / rel_path
        if not abs_path.exists():
            continue
        for raw in _iter_event_stream_entries(abs_path, adapter):
            event_name = str(
                raw.get("event_name")
                or raw.get("event")
                or raw.get("type")
                or adapter.get("event_name", "knowledge.event")
            )
            if patterns and not any(fnmatch(event_name, pattern) for pattern in patterns):
                continue
            if filters and not _matches_payload_filters(raw, filters):
                continue
            event_id = _stream_event_id(adapter, rel_path, raw)
            if event_id in processed:
                continue
            observed_at = str(
                raw.get("occurred_at") or raw.get("observed_at") or now_utc().isoformat()
            )
            status_value = _lookup_dotted(raw, status_field)
            status = (
                str(status_value)
                if status_value is not None
                else str(raw.get("status", "observed"))
            )
            details = {
                "payload": raw.get("payload", {}) if isinstance(raw.get("payload"), dict) else {},
                "source_system": raw.get("source_system"),
                "raw_event": raw,
            }
            events.append(
                EventRecord(
                    event_id=event_id,
                    adapter_id=str(adapter.get("id", "unknown")),
                    event_name=event_name,
                    source_path=rel_path,
                    status=status,
                    observed_at=observed_at,
                    affected_pages=[str(x) for x in adapter.get("affects_pages", []) or []],
                    fingerprint_before=None,
                    fingerprint_now=_fingerprint_text(
                        json.dumps(raw, sort_keys=True, ensure_ascii=False)
                    ),
                    summary=_build_event_stream_summary(adapter, rel_path, raw, summary_fields),
                    diff_excerpt=None,
                    details=details,
                )
            )
    return events


def _iter_event_stream_entries(path: Path, adapter: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        record.setdefault("_stream_line", line_number)
        yield record


def _write_event_proposal(
    config: KnowledgeConfig, page_id: str, events: list[EventRecord], *, mode: str
) -> Path:
    timestamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    proposal_path = config.proposals_root / f"{timestamp}-{page_id}-event-review.yml"
    payload = {
        "proposal_id": f"{timestamp}-{page_id}-event-review",
        "proposal_kind": "event_review",
        "proposal_mode": mode,
        "target_page_id": page_id,
        "generated_at": now_utc().isoformat(),
        "summary": f"Planning/runtime event drift detected for {page_id}. Review the current-state page.",
        "events": [
            {
                "event_id": event.event_id,
                "adapter_id": event.adapter_id,
                "event_name": event.event_name,
                "source_path": event.source_path,
                "status": event.status,
                "summary": event.summary,
                "details": event.details,
                "diff_excerpt": event.diff_excerpt,
            }
            for event in events
        ],
        "suggested_steps": [
            "Review the event source change.",
            "Update the current-state page only if durable behavior changed.",
            "Keep draft or incomplete work out of current-state pages.",
            "Record fresh sync and event baselines after review.",
        ],
        "actions": [],
    }
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(dump_yaml(payload), encoding="utf-8")
    return proposal_path


def _resolve_relative_paths(config: KnowledgeConfig, adapter: dict[str, Any]) -> list[str]:
    results: list[str] = []
    for pattern in [str(x) for x in adapter.get("path_globs", []) or []]:
        if any(ch in pattern for ch in "*?["):
            for path in config.root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(config.root).as_posix()
                if fnmatch(rel, pattern):
                    results.append(rel)
        else:
            target = config.root / pattern
            if target.is_file():
                results.append(Path(pattern).as_posix())
    return sorted(dict.fromkeys(results))


def _event_id(adapter: dict[str, Any], rel_path: str, fingerprint: str) -> str:
    return f"{adapter.get('id', 'adapter')}::{rel_path}::{fingerprint[:16]}"


def _build_summary(adapter: dict[str, Any], rel_path: str, details: dict[str, Any]) -> str:
    prefix = str(adapter.get("summary_prefix", adapter.get("event_name", "Event")))
    fragments = [f"{prefix}: {rel_path}"]
    if details.get("changed_keys"):
        fragments.append(f"changed keys: {', '.join(details['changed_keys'])}")
    if details.get("added_keys"):
        fragments.append(f"added keys: {', '.join(details['added_keys'])}")
    if details.get("removed_keys"):
        fragments.append(f"removed keys: {', '.join(details['removed_keys'])}")
    if details.get("added_headings"):
        fragments.append(f"added headings: {', '.join(details['added_headings'])}")
    if details.get("removed_headings"):
        fragments.append(f"removed headings: {', '.join(details['removed_headings'])}")
    return " | ".join(fragments)


def _build_event_stream_summary(
    adapter: dict[str, Any], rel_path: str, raw: dict[str, Any], summary_fields: list[str]
) -> str:
    prefix = str(
        adapter.get(
            "summary_prefix",
            raw.get("event_name") or adapter.get("event_name", "Event stream event"),
        )
    )
    fragments = [f"{prefix}: {rel_path}"]
    for field in summary_fields:
        value = _lookup_dotted(raw, field)
        if value is not None and value != "":
            fragments.append(f"{field}={value}")
    return " | ".join(fragments)


def _append_event_journal(config: KnowledgeConfig, event: EventRecord) -> None:
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
    state: dict[str, Any], source_path: Path, event: EventRecord, adapter: dict[str, Any]
) -> None:
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


def _event_stream_source_state(adapter: dict[str, Any], source_path: Path) -> dict[str, Any]:
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


def _adapter_by_id(config: KnowledgeConfig, adapter_id: str) -> dict[str, Any] | None:
    for adapter in load_event_adapters(config):
        if str(adapter.get("id")) == adapter_id:
            return adapter
    return None


def _fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _adapter_source_kind(adapter: dict[str, Any]) -> str:
    return str(adapter.get("source_kind", "file_change")).strip() or "file_change"


def _stream_event_id(adapter: dict[str, Any], rel_path: str, raw: dict[str, Any]) -> str:
    explicit = raw.get("event_id")
    if explicit:
        return str(explicit)
    material = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{adapter.get('id', 'adapter')}::{rel_path}::stream::{digest}"


def _lookup_dotted(data: Any, dotted: str) -> Any:
    current = data
    for segment in [seg for seg in dotted.split(".") if seg]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _matches_payload_filters(raw: dict[str, Any], filters: dict[str, Any]) -> bool:
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


# Event handler for planning state changes (task-0282, task-0289)
def on_planning_state_change(
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """Handle planning.item.state.changed events.

    Triggers knowledge sync actions based on planning state changes:
    - task done/verified → mark related pages stale
    - wp done → generate sync proposal for plan
    - plan done → review spec/overview pages
    - blocked → mark operational pages stale

    Args:
        event_type: Event type string
        payload: Event payload with old_state, new_state, subject
        metadata: Event metadata with is_replay flag
    """
    root = Path.cwd()
    config = load_config(root)

    # Skip replayed events unless interoperability config explicitly allows dispatch
    if metadata.get("is_replay"):
        if not _dispatch_on_replay_enabled(root):
            return

    subject = metadata.get("subject", {}) if isinstance(metadata.get("subject"), dict) else {}
    if not subject and isinstance(payload.get("subject"), dict):
        subject = payload.get("subject", {})

    kind = subject.get("kind")
    new_state = payload.get("new_state")
    item_id = subject.get("id") or payload.get("id")

    if not kind or not item_id or not new_state:
        return

    event = _build_runtime_planning_event(
        config=config,
        event_type=event_type,
        payload=payload,
        metadata=metadata,
        kind=str(kind),
        item_id=str(item_id),
        new_state=str(new_state),
    )
    if event is None:
        return

    _process_runtime_planning_event(config, event)


def _build_runtime_planning_event(
    *,
    config: KnowledgeConfig,
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
    kind: str,
    item_id: str,
    new_state: str,
) -> EventRecord | None:
    """Build a synthetic EventRecord for in-process planning state changes."""
    raw_event = {
        "event": event_type,
        "event_name": event_type,
        "id": item_id,
        "subject": {"kind": kind, "id": item_id},
        **payload,
        "metadata": metadata,
    }
    correlation_id = metadata.get("correlation_id", "manual")
    event_id = f"runtime-planning::{event_type}::{kind}::{item_id}::{new_state}::{correlation_id}"

    state = load_event_state(config)
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    if event_id in processed:
        return None

    adapter = _select_runtime_planning_adapter(config, event_type)
    affected_pages = [str(x) for x in adapter.get("affects_pages", []) or []]
    if not affected_pages:
        affected_pages = list(DEFAULT_PLANNING_AFFECTED_PAGES)

    return EventRecord(
        event_id=event_id,
        adapter_id=str(adapter.get("id", "runtime-planning-state-change")),
        event_name=event_type,
        source_path=".audiagentic/planning/events/events.jsonl",
        status=new_state,
        observed_at=now_utc().isoformat(),
        affected_pages=affected_pages,
        summary=f"Planning {kind} {item_id} state changed to {new_state}",
        details={
            "payload": payload,
            "metadata": metadata,
            "raw_event": raw_event,
            "source_system": "planning-runtime",
        },
    )


def _select_runtime_planning_adapter(config: KnowledgeConfig, event_type: str) -> dict[str, Any]:
    """Pick the configured adapter that best represents planning state changes."""
    for adapter in load_event_adapters(config):
        patterns = [str(x) for x in adapter.get("event_name_patterns", []) or []]
        if patterns and any(fnmatch(event_type, pattern) for pattern in patterns):
            return adapter
    return {"id": "runtime-planning-state-change", "affects_pages": DEFAULT_PLANNING_AFFECTED_PAGES}


def _process_runtime_planning_event(config: KnowledgeConfig, event: EventRecord) -> dict[str, Any]:
    """Apply configured knowledge actions for an in-process planning event."""
    state = load_event_state(config)
    action_registry = load_event_action_registry(config)
    handlers_config = load_event_handlers(config)
    adapter = _select_runtime_planning_adapter(config, event.event_name)
    handler_config = _match_event_handler(event, handlers_config)
    action_name = str(handler_config.get("action", "generate_sync_proposal"))
    handler, defaults = resolve_registry_handler(action_registry, action_name)
    runtime_action = {
        **defaults,
        **(handler_config.get("action_args", {}) if isinstance(handler_config, dict) else {}),
    }
    context: dict[str, Any] = {
        "generated_proposals": [],
        "marked_stale_pages": set(),
        "handled": [event.event_id],
        "page_event_map": {},
        "applied_proposals": [],
    }
    handler(
        config=config,
        event=event,
        adapter=adapter,
        state=state,
        context=context,
        action_args=runtime_action,
    )
    if config.auto_mark_stale and context["marked_stale_pages"]:
        mark_pages_stale(config, sorted(context["marked_stale_pages"]))
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    processed.add(event.event_id)
    save_event_state(config, {**state, "processed_event_ids": sorted(processed)})
    _append_event_journal(config, event)
    return {
        "processed_event_ids": list(context["handled"]),
        "marked_stale_pages": sorted(context["marked_stale_pages"]),
        "generated_proposals": context["generated_proposals"],
    }


def _dispatch_on_replay_enabled(root: Path) -> bool:
    """Check interoperability replay config without importing the runtime module."""
    raw = load_yaml_file(root / ".audiagentic" / "interoperability" / "config.yaml", {})
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("runtime", {}).get("replay", {}).get("dispatch_on_replay", False))
