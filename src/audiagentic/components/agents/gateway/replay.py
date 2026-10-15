"""Causal recovery intents and offline replay analysis (GA04)."""
from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_recovery_action_path,
    gateway_request_path,
)
from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z

SCHEMA_VERSION = "gateway-recovery.v1"
_PAGE_SIZE = 100


def _text(value: Any, limit: int = 256) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _lock(project_root: Path, request_id: str) -> StartupLock:
    return StartupLock(gateway_request_path(project_root, request_id).with_name("mutation.lock"))


def _read(project_root: Path, request_id: str) -> list[dict[str, Any]]:
    return load_ndjson(gateway_recovery_action_path(project_root, request_id))


def _append(project_root: Path, request_id: str, event: dict[str, Any]) -> dict[str, Any]:
    path = gateway_recovery_action_path(project_root, request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _read(project_root, request_id)
    event = dict(event)
    event["event-seq"] = (int(entries[-1].get("event-seq", 0)) if entries else 0) + 1
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def prepare_recovery_action(
    project_root: Path,
    request_id: str,
    *,
    action_attempt_id: str,
    action: str,
    attempt_epoch: int,
    retry_budget: int,
    submission_proven: bool | None,
    action_kind: str = "provider-native-continue",
    causal_input_ids: Iterable[str] = (),
    binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist action intent before a side effect and fence ambiguous replay."""
    if not action_attempt_id or not action:
        raise ValueError("action and action_attempt_id are required")
    if retry_budget < 0:
        raise ValueError("retry budget cannot be negative")
    if action_kind not in {"provider-native-retry", "provider-native-continue", "linked-child-turn", "reconcile"}:
        raise ValueError("unknown recovery action kind")
    with _lock(project_root, request_id):
        entries = _read(project_root, request_id)
        for entry in entries:
            if entry.get("action-attempt-id") == action_attempt_id:
                return entry
        if action_kind in {"provider-native-retry", "provider-native-continue"} and submission_proven is not False:
            disposition, outcome = "reconciliation-required", "rejected-ambiguous-submission"
        elif retry_budget == 0 and action_kind != "reconcile":
            disposition, outcome = "budget-exhausted", "rejected-retry-budget"
        else:
            disposition, outcome = "intent-persisted", "pending-side-effect"
        safe_binding = {
            key: value for key in ("project-id", "session-id", "chat-id", "turn-id", "prompt-fingerprint")
            if isinstance((value := (binding or {}).get(key)), (str, int, bool))
        }
        event = {
            "schema-version": SCHEMA_VERSION,
            "event": "action-intent",
            "action-attempt-id": _text(action_attempt_id, 128),
            "action": _text(action, 128),
            "action-kind": action_kind,
            "attempt-epoch": max(1, int(attempt_epoch)),
            "retry-budget": int(retry_budget),
            "submission-proven": submission_proven,
            "disposition": disposition,
            "outcome": outcome,
            "causal-input-ids": [_text(value, 128) for value in causal_input_ids if _text(value, 128)],
            "binding": safe_binding,
            "created-at": now_iso_z(),
        }
        return _append(project_root, request_id, event)


def record_recovery_result(
    project_root: Path,
    request_id: str,
    *,
    action_attempt_id: str,
    outcome: str,
    terminal: bool = False,
    causal_input_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Append reconciliation/result evidence; never mutate the intent event."""
    with _lock(project_root, request_id):
        entries = _read(project_root, request_id)
        if not any(item.get("action-attempt-id") == action_attempt_id for item in entries):
            raise ValueError("recovery action intent is missing")
        return _append(
            project_root,
            request_id,
            {
                "schema-version": SCHEMA_VERSION,
                "event": "action-result",
                "action-attempt-id": _text(action_attempt_id, 128),
                "outcome": _text(outcome, 128) or "unknown",
                "terminal": bool(terminal),
                "causal-input-ids": [_text(value, 128) for value in causal_input_ids if _text(value, 128)],
                "created-at": now_iso_z(),
            },
        )


def prove_turn_correlation(
    record: Mapping[str, Any],
    *,
    project_id: str | None,
    session_id: str | None,
    chat_id: str | None,
    turn_id: str | None,
    prompt_fingerprint: str | None,
    assistant_id: str | None,
    assistant_pinned: bool,
    assistant_remounted: bool,
    terminal_witness_id: str | None,
) -> dict[str, Any]:
    """Return strong ownership proof; provenance keys alone never suffice."""
    def value(name: str) -> Any:
        return record.get(name) if name in record else record.get(name.replace("-", "_"))

    expected = {
        "project-id": project_id,
        "session-id": session_id,
        "chat-id": chat_id,
        "turn-id": turn_id,
    }
    mismatches = [key for key, expected_value in expected.items() if expected_value is not None and value(key) != expected_value]
    prompt_proven = bool(prompt_fingerprint and value("prompt-fingerprint") == prompt_fingerprint)
    assistant_boundary = bool(assistant_id and (assistant_pinned or assistant_remounted))
    terminal_witness = bool(terminal_witness_id and assistant_id and terminal_witness_id == assistant_id)
    proof = {
        "project-session-chat-bound": not mismatches,
        "prompt-identity-proven": prompt_proven,
        "assistant-boundary-proven": assistant_boundary,
        "terminal-witness-proven": terminal_witness,
        "mismatches": mismatches,
    }
    proof["strong"] = all(proof[key] for key in ("project-session-chat-bound", "prompt-identity-proven", "assistant-boundary-proven", "terminal-witness-proven"))
    return proof


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"v": 1, "offset": offset}, separators=(",", ":")).encode()).decode().rstrip("=")


def _offset(cursor: str | None, total: int) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        offset = value["offset"]
        if value.get("v") != 1 or isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= total:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid recovery cursor") from exc


def read_recovery_page(project_root: Path, request_id: str, *, limit: int = 25, cursor: str | None = None) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _PAGE_SIZE:
        raise ValueError("recovery limit must be an integer between 1 and 100")
    entries = _read(project_root, request_id)
    start = _offset(cursor, len(entries))
    items = entries[start : start + limit]
    result = {
        "schema-version": SCHEMA_VERSION,
        "request-id": request_id,
        "items": items,
        "returned": len(items),
    }
    if start + len(items) < len(entries):
        result["next-cursor"] = _cursor(start + len(items))
    return result


def replay_observations(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Analyze captured journals without CDP or lifecycle mutation."""
    rows = list(entries)
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"observations": 0, "errors": 0, "resolved": 0, "actions": 0, "action-success": 0})
    first_activity: int | None = None
    for row in rows:
        facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
        activity = facts.get("activity") if isinstance(facts, Mapping) else {}
        if first_activity is None and isinstance(activity, Mapping) and activity:
            first_activity = int(row.get("monotonic_ms", 0))
        error = facts.get("error-occurrence") if isinstance(facts, Mapping) else {}
        error_code = "none"
        if isinstance(error, Mapping):
            error_code = _text(error.get("code"), 128) or _text(error.get("classification"), 128) or "none"
        bucket = groups[error_code]
        bucket["observations"] += 1
        if error_code != "none":
            bucket["errors"] += 1
        decision = facts.get("decision") if isinstance(facts, Mapping) else {}
        if isinstance(decision, Mapping) and decision.get("outcome") in {"completed", "resolved", "terminal-success"}:
            bucket["resolved"] += 1
        action = facts.get("action") if isinstance(facts, Mapping) else {}
        if isinstance(action, Mapping) and action:
            bucket["actions"] += 1
            if action.get("outcome") in {"accepted", "completed", "success"}:
                bucket["action-success"] += 1
    total_errors = sum(value["errors"] for value in groups.values())
    resolved = sum(value["resolved"] for value in groups.values())
    return {
        "schema-version": SCHEMA_VERSION,
        "observations": len(rows),
        "groups": dict(groups),
        "resolution-rate": (resolved / total_errors) if total_errors else None,
        "first-activity-monotonic-ms": first_activity,
        "stop-disappearance-is-observation": True,
    }


def replay_request(project_root: Path, request_id: str, *, observations: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Produce a deterministic, fail-closed replay decision."""
    actions = _read(project_root, request_id)
    intents = {item.get("action-attempt-id"): item for item in actions if item.get("event") == "action-intent"}
    results = {item.get("action-attempt-id") for item in actions if item.get("event") == "action-result"}
    pending = [item for key, item in intents.items() if key and key not in results]
    original_errors = []
    for row in observations:
        facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
        error = facts.get("error-occurrence") if isinstance(facts, Mapping) else None
        if isinstance(error, Mapping) and error:
            original_errors.append({key: error[key] for key in ("code", "classification", "occurrence-id") if key in error})
    analysis = replay_observations(observations)
    analysis.update({
        "request-id": request_id,
        "pending-action-attempts": [item.get("action-attempt-id") for item in pending],
        "original-errors": original_errors[:32],
        "recovery-decision": "reconciliation-required" if pending else "observation-only",
        "safe-to-resubmit": False,
        "duplicate-prompt-fence": "ambiguous-action-attempt" if pending else "no-automatic-resubmit",
    })
    return analysis


__all__ = [
    "SCHEMA_VERSION",
    "prepare_recovery_action",
    "prove_turn_correlation",
    "read_recovery_page",
    "record_recovery_result",
    "replay_observations",
    "replay_request",
]
