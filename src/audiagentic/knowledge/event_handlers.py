"""Event processing pipeline and action handlers.

Dispatches events to configured handlers, executes built-in actions,
handles planning state change events.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .config import KnowledgeConfig
from .event_scanner import (
    _write_event_proposal,
    scan_events,
)
from .event_state import (
    _adapter_by_id,
    _append_event_journal,
    _matches_payload_filters,
    _record_event_source,
    load_event_adapters,
    load_event_state,
    save_event_state,
)
from .hooks import evaluate_source
from .models import EventRecord
from .registry import load_event_action_registry, resolve_registry_handler
from .sync import mark_pages_stale
from .utils import load_yaml_file, now_utc

DEFAULT_PLANNING_AFFECTED_PAGES = [
    "system-planning",
    "system-knowledge",
    "guide-using-planning",
    "tool-cli",
    "tool-mcp",
    "pattern-event-bridge",
    "pattern-page-lifecycle",
]


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
    """Scan, match, and process events through configured handlers."""
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
    """Action: generate sync proposal for affected pages."""
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
    """Action: mark affected pages as stale."""
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
    """Action: mark stale and generate proposal."""
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
    """Action: do nothing."""
    return None


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
    from .config import load_config

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
    from .utils import load_yaml_file

    raw = load_yaml_file(root / ".audiagentic" / "interoperability" / "config.yaml", {})
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("runtime", {}).get("replay", {}).get("dispatch_on_replay", False))
