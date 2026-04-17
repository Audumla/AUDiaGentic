"""Event scanning and proposal generation.

Detects source file changes and event stream entries, generates sync proposals.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .config import KnowledgeConfig
from .diffing import normalize_text, summarize_structured_change, unified_diff_excerpt
from .event_state import (
    _adapter_source_kind,
    _event_id,
    _event_stream_source_state,
    _fingerprint_text,
    _lookup_dotted,
    _matches_payload_filters,
    _stream_event_id,
    load_event_adapters,
    load_event_state,
    save_event_state,
)
from .markdown_io import load_page_by_id
from .models import EventRecord
from .utils import dump_yaml, now_utc


def record_event_baseline(config: KnowledgeConfig) -> dict[str, Any]:
    """Record initial fingerprints of all source files."""
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
    """Scan all sources for changes."""
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


def _scan_file_change_adapter(
    config: KnowledgeConfig, adapter: dict[str, Any], state: dict[str, Any]
) -> list[EventRecord]:
    """Scan file change adapter for modified sources."""
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
    """Scan event stream adapter for new entries."""
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
        source_state = state.get("sources", {}).get(rel_path, {})
        last_stream_line = (
            int(source_state.get("last_stream_line", 0))
            if isinstance(source_state, dict)
            else 0
        )
        total_lines = sum(
            1
            for line in abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        )
        if total_lines < last_stream_line:
            last_stream_line = 0
        for raw in _iter_event_stream_entries(abs_path, adapter):
            if int(raw.get("_stream_line", 0)) <= last_stream_line:
                continue
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
    """Iterate JSON lines from event stream file."""
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
    """Write event proposal YAML file."""
    timestamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    assessment = _assess_event_proposal(config, page_id, events)
    payload = {
        "proposal_kind": "event_review",
        "proposal_mode": mode,
        "target_page_id": page_id,
        "generated_at": now_utc().isoformat(),
        "status": "pending",
        "status_updated_at": now_utc().isoformat(),
        "summary": f"Planning/runtime event drift detected for {page_id}. Review the current-state page.",
        "assessment": assessment,
        "recommendation": assessment["recommended_action"],
        "affected_sections": assessment["affected_sections"],
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
            *assessment["suggested_steps"],
            "Record fresh sync and event baselines after review.",
        ],
        "actions": assessment["actions"],
    }
    dedupe_key = _event_proposal_dedupe_key(payload)
    existing_path = _find_existing_event_proposal(config, page_id, dedupe_key)
    if existing_path is not None:
        return existing_path
    proposal_path = config.proposals_root / f"{timestamp}-{page_id}-event-review.yml"
    payload["proposal_id"] = f"{timestamp}-{page_id}-event-review"
    payload["dedupe_key"] = dedupe_key
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(dump_yaml(payload), encoding="utf-8")
    return proposal_path


def _resolve_relative_paths(config: KnowledgeConfig, adapter: dict[str, Any]) -> list[str]:
    """Expand glob patterns to relative file paths."""
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


def _build_summary(adapter: dict[str, Any], rel_path: str, details: dict[str, Any]) -> str:
    """Build human-readable event summary."""
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
    """Build human-readable event stream summary."""
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


def _assess_event_proposal(
    config: KnowledgeConfig, page_id: str, events: list[EventRecord]
) -> dict[str, Any]:
    page = load_page_by_id(config.pages_root, config.meta_root, page_id)
    section_titles = [section.title for section in page.sections] if page else []
    event_states = [str(event.status) for event in events]
    durable_states = {"done", "verified", "archived", "superseded"}
    durable = any(state in durable_states for state in event_states)
    likely_requires_doc_change = durable
    confidence = "high" if durable or event_states else "medium"
    recommended_action = "review_update" if durable else "reject_no_doc_change"
    reason = (
        "Event reached a durable lifecycle state that may change current-state documentation."
        if durable
        else "Event appears to be workflow churn without a durable behavior change."
    )
    affected_sections = _select_affected_sections(section_titles, durable)
    actions = _build_assessment_actions(affected_sections, durable)
    suggested_steps = (
        [
            "Review the event source change.",
            "Confirm whether durable behavior changed.",
            "Update the highlighted sections if current-state docs are now stale.",
        ]
        if durable
        else [
            "Review the event source change.",
            "Reject this proposal unless the workflow state caused a real user-facing behavior change.",
            "Keep in-progress or transient execution churn out of current-state pages.",
        ]
    )
    return {
        "likely_requires_doc_change": likely_requires_doc_change,
        "reason": reason,
        "confidence": confidence,
        "recommended_action": recommended_action,
        "affected_sections": affected_sections,
        "state_sequence": event_states,
        "actions": actions,
        "suggested_steps": suggested_steps,
    }


def _select_affected_sections(section_titles: list[str], durable: bool) -> list[str]:
    preferred = ["Current state", "How to use", "Sync notes", "References"]
    if not durable:
        preferred = ["Sync notes", "References"]
    matched = [title for title in preferred if title in section_titles]
    return matched or section_titles[:2]


def _build_assessment_actions(affected_sections: list[str], durable: bool) -> list[dict[str, Any]]:
    if not durable:
        return []
    return [
        {
            "action": "review_section",
            "section": section,
            "intent": "confirm current-state documentation still matches durable runtime behavior",
        }
        for section in affected_sections
    ]


def _event_proposal_dedupe_key(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("proposal_id", None)
    normalized.pop("generated_at", None)
    normalized.pop("status_updated_at", None)
    normalized.pop("dedupe_key", None)
    material = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _find_existing_event_proposal(
    config: KnowledgeConfig, page_id: str, dedupe_key: str
) -> Path | None:
    if not config.proposals_root.exists():
        return None
    for proposal_path in sorted(config.proposals_root.glob(f"*-{page_id}-event-review.yml")):
        try:
            import yaml

            proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(proposal, dict):
            continue
        if proposal.get("proposal_kind") != "event_review":
            continue
        if proposal.get("status", "pending") != "pending":
            continue
        existing_key = proposal.get("dedupe_key")
        if not existing_key:
            existing_key = _event_proposal_dedupe_key(proposal)
        if existing_key == dedupe_key:
            return proposal_path
    return None
