"""Causal recovery intents and offline replay analysis (GA04)."""
from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_recovery_action_path,
    gateway_recovery_index_path,
    gateway_request_path,
)
from audiagentic.foundation.io import iter_ndjson, last_ndjson
from audiagentic.foundation.observability.journal_segments import has_segments, head_read_lock
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import is_meaningful_activity_label

SCHEMA_VERSION = "gateway-recovery.v1"
_PAGE_SIZE = 100
RECOVERY_CLAIM_LEASE_SECONDS = 120.0
RECOVERY_UNRESOLVED_COOLDOWN_SECONDS = 60.0
_RECOVERY_CLOCK_SKEW_SECONDS = 5.0


class RecoveryClaimLostError(RuntimeError):
    """Raised when a recovery worker no longer owns its durable claim."""


def _text(value: Any, limit: int = 256) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _parse_recovery_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def recovery_claim_state(
    entries: Iterable[Mapping[str, Any]], *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Project the authoritative reconciliation claim from journal order."""
    current: dict[str, Any] | None = None
    generation = 0
    for entry in entries:
        if entry.get("event") == "action-intent" and entry.get("action-kind") == "reconcile" and entry.get("disposition") == "intent-persisted":
            raw_generation = entry.get("claim-generation")
            generation = raw_generation if isinstance(raw_generation, int) and not isinstance(raw_generation, bool) else generation + 1
            current = {
                "action-attempt-id": entry.get("action-attempt-id"),
                "claim-generation": generation,
                "lease-expires-at": entry.get("lease-expires-at"),
                "intent": dict(entry),
                "result": None,
                "lease-created-at": entry.get("created-at"),
            }
        elif current is not None and entry.get("event") == "claim-renewal" and entry.get("action-attempt-id") == current["action-attempt-id"] and entry.get("claim-generation") == current["claim-generation"]:
            current["lease-expires-at"] = entry.get("lease-expires-at")
            current["lease-created-at"] = entry.get("created-at")
        elif current is not None and entry.get("event") == "action-result" and entry.get("action-attempt-id") == current["action-attempt-id"] and entry.get("claim-generation") == current["claim-generation"]:
            current["result"] = dict(entry)
    if current is None:
        return None
    current["created-at"] = current["intent"].get("created-at")
    reference = now or datetime.now(timezone.utc)
    created = _parse_recovery_time(current.get("created-at"))
    lease_created = _parse_recovery_time(current.get("lease-created-at"))
    expires = _parse_recovery_time(current.get("lease-expires-at"))
    current["valid"] = bool(
        created
        and lease_created
        and expires
        and created <= reference + timedelta(seconds=_RECOVERY_CLOCK_SKEW_SECONDS)
        and lease_created <= reference + timedelta(seconds=_RECOVERY_CLOCK_SKEW_SECONDS)
        and expires >= lease_created
        and expires <= lease_created + timedelta(
            seconds=RECOVERY_CLAIM_LEASE_SECONDS + _RECOVERY_CLOCK_SKEW_SECONDS
        )
    )
    current["invalid-reason"] = None if current["valid"] else "invalid-claim-timestamps"
    current["active"] = bool(current["valid"] and expires and expires > reference)
    return current


def assert_recovery_claim_owner(
    project_root: Path,
    request_id: str,
    *,
    action_attempt_id: str,
    claim_generation: int,
) -> dict[str, Any]:
    """Fail closed unless this attempt owns the current, unexpired claim."""
    with _lock(project_root, request_id):
        claim = recovery_claim_state(_read(project_root, request_id), now=datetime.now(timezone.utc))
        if not claim or not claim.get("valid") or not claim.get("active") or claim.get("action-attempt-id") != action_attempt_id or claim.get("claim-generation") != claim_generation or claim.get("result") is not None:
            raise RecoveryClaimLostError("recovery claim is no longer owned")
        return claim


def renew_recovery_claim(
    project_root: Path,
    request_id: str,
    *,
    action_attempt_id: str,
    claim_generation: int,
) -> bool:
    """Extend an owned claim without changing its generation."""
    with _lock(project_root, request_id):
        claim = recovery_claim_state(_read(project_root, request_id), now=datetime.now(timezone.utc))
        if not claim or not claim.get("valid") or not claim.get("active") or claim.get("action-attempt-id") != action_attempt_id or claim.get("claim-generation") != claim_generation or claim.get("result") is not None:
            return False
        expires = (datetime.now(timezone.utc) + timedelta(seconds=RECOVERY_CLAIM_LEASE_SECONDS)).isoformat().replace("+00:00", "Z")
        _append(project_root, request_id, {"schema-version": SCHEMA_VERSION, "event": "claim-renewal", "action-attempt-id": action_attempt_id, "claim-generation": claim_generation, "lease-expires-at": expires, "created-at": now_iso_z()})
        return True


def _lock(project_root: Path, request_id: str) -> StartupLock:
    return StartupLock(gateway_request_path(project_root, request_id).with_name("mutation.lock"))


def recovery_capture_lock(
    project_root: Path, request_id: str, *, timeout: float = 0.25
) -> StartupLock:
    """Return the cross-process mutex for one provider response capture.

    The durable claim decides *which* recovery attempt may proceed; this
    mutex prevents a stale worker and a takeover worker from entering the
    provider runtime concurrently while the first attempt is still unwinding.
    """
    return StartupLock(
        gateway_request_path(project_root, request_id).with_name(
            "recovery-capture.lock"
        ),
        timeout=timeout,
    )


def _read(project_root: Path, request_id: str) -> list[dict[str, Any]]:
    return list(iter_ndjson(gateway_recovery_action_path(project_root, request_id)))


def _append(project_root: Path, request_id: str, event: dict[str, Any]) -> dict[str, Any]:
    from audiagentic.foundation.observability.journal_segments import journal_lock

    path = gateway_recovery_action_path(project_root, request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with journal_lock(path):
        return _append_locked(project_root, request_id, event)


def _append_locked(project_root: Path, request_id: str, event: dict[str, Any]) -> dict[str, Any]:
    from audiagentic.foundation.observability.journal_segments import (
        journal_sequence_watermark,
        prepare_append,
    )

    from .retention import journal_max_bytes

    path = gateway_recovery_action_path(project_root, request_id)
    previous = last_ndjson(gateway_recovery_action_path(project_root, request_id))
    event = dict(event)
    event["event-seq"] = (int(previous.get("event-seq", 0)) if previous else journal_sequence_watermark(path)) + 1
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    index = gateway_recovery_index_path(project_root, request_id)
    prepare_append(path, index, max_bytes=journal_max_bytes("recovery"),
                   incoming_bytes=len(line.encode("utf-8")))
    offset = path.stat().st_size if path.exists() else 0
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"event-seq": event["event-seq"], "offset": offset, "length": len(line.encode("utf-8"))}, separators=(",", ":")) + "\n")
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
        entries = list(iter_ndjson(gateway_recovery_action_path(project_root, request_id)))
        existing: dict[str, Any] | None = None
        result_seen = False
        consumed_budget = 0
        for entry in entries:
            if entry.get("action-attempt-id") == action_attempt_id:
                existing = entry
            if entry.get("event") == "action-result" and entry.get("action-attempt-id") == action_attempt_id:
                result_seen = True
            if entry.get("event") == "action-intent" and entry.get("action-kind") in {"provider-native-retry", "provider-native-continue"} and entry.get("disposition") == "intent-persisted":
                consumed_budget += 1
        if existing is not None:
            if existing.get("event") == "action-intent" and existing.get("disposition") == "intent-persisted":
                if result_seen:
                    return {**existing, "disposition": "already-recorded", "outcome": "action-already-recorded"}
                return {**existing, "disposition": "reconciliation-required", "outcome": "action-result-missing"}
            return existing
        claim_generation = None
        if action_kind == "reconcile":
            now = datetime.now(timezone.utc)
            claim = recovery_claim_state(entries, now=now)
            if claim:
                prior_result = claim.get("result")
                if prior_result is not None:
                    outcome = prior_result.get("outcome")
                    created = _parse_recovery_time(prior_result.get("created-at"))
                    if outcome == "reconciliation-completed":
                        return {**claim["intent"], **prior_result, "disposition": "already-recorded"}
                    if created is None or created > now + timedelta(seconds=_RECOVERY_CLOCK_SKEW_SECONDS):
                        return {**claim["intent"], **prior_result, "disposition": "reconciliation-required", "outcome": "recovery-timestamp-invalid"}
                    if (now - created).total_seconds() < RECOVERY_UNRESOLVED_COOLDOWN_SECONDS:
                        return {**claim["intent"], **prior_result, "disposition": "reconciliation-required", "outcome": "recovery-cooldown-active"}
                elif not claim.get("valid"):
                    # A malformed/future lease cannot prove another observer
                    # still owns the reconciliation claim. Reconcile is
                    # read-only with respect to provider prompts; advance the
                    # generation so stale workers fail their owner fence.
                    prior_generation = claim.get("claim-generation")
                    claim_generation = (
                        prior_generation
                        if isinstance(prior_generation, int)
                        and not isinstance(prior_generation, bool)
                        and prior_generation > 0
                        else 0
                    ) + 1
                elif claim.get("active"):
                    return {**claim["intent"], "disposition": "reconciliation-required", "outcome": "recovery-claim-active"}
                else:
                    claim_generation = int(claim.get("claim-generation") or 0) + 1
            else:
                claim_generation = 1
        remaining_budget = max(0, int(retry_budget) - consumed_budget)
        if action_kind in {"provider-native-retry", "provider-native-continue"} and submission_proven is not False:
            disposition, outcome = "reconciliation-required", "rejected-ambiguous-submission"
        elif remaining_budget == 0 and action_kind != "reconcile":
            disposition, outcome = "budget-exhausted", "rejected-retry-budget"
        else:
            disposition, outcome = "intent-persisted", "pending-side-effect"
        safe_binding = {
            key: value for key in (
                "project-id", "session-id", "chat-id", "turn-id", "prompt-fingerprint",
                "assistant-id", "terminal-witness-id", "provider-session-id", "provider-turn-id",
            )
            if isinstance((value := (binding or {}).get(key)), (str, int, bool))
        }
        event = {
            "schema-version": SCHEMA_VERSION,
            "event": "action-intent",
            "action-attempt-id": _text(action_attempt_id, 128),
            "action": _text(action, 128),
            "action-kind": action_kind,
            "attempt-epoch": max(1, int(attempt_epoch)),
            "retry-budget": remaining_budget if action_kind != "reconcile" else int(retry_budget),
            "retry-budget-before": int(retry_budget),
            "submission-proven": submission_proven,
            "disposition": disposition,
            "outcome": outcome,
            "causal-input-ids": [_text(value, 128) for value in causal_input_ids if _text(value, 128)],
            "binding": safe_binding,
            "created-at": now_iso_z(),
        }
        if action_kind == "reconcile" and disposition == "intent-persisted":
            event["claim-generation"] = claim_generation or 1
            event["claim-owner-id"] = event["action-attempt-id"]
            created = _parse_recovery_time(event["created-at"])
            if created is not None:
                event["lease-expires-at"] = (
                    created + timedelta(seconds=RECOVERY_CLAIM_LEASE_SECONDS)
                ).isoformat().replace("+00:00", "Z")
        result = _append(project_root, request_id, event)
    try:
        from .observability import append_observation
        append_observation(
            project_root,
            request_id,
            attempt_epoch=attempt_epoch,
            source="recovery-intent",
            action={"event": "action-intent", "kind": action_kind, "outcome": outcome},
            causal_input_ids=[request_id, action_attempt_id],
        )
    except Exception:  # noqa: BLE001 - recovery journal remains authoritative
        pass
    return result


def record_recovery_result(
    project_root: Path,
    request_id: str,
    *,
    action_attempt_id: str,
    outcome: str,
    terminal: bool = False,
    claim_generation: int | None = None,
    causal_input_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Append reconciliation/result evidence; never mutate the intent event."""
    with _lock(project_root, request_id):
        entries = list(iter_ndjson(gateway_recovery_action_path(project_root, request_id)))
        intent = next((entry for entry in entries if entry.get("event") == "action-intent" and entry.get("action-attempt-id") == action_attempt_id), None)
        if intent is None:
            raise ValueError("recovery action intent is missing")
        resolved_generation = claim_generation if isinstance(claim_generation, int) else intent.get("claim-generation")
        existing_result = next((entry for entry in entries if entry.get("event") == "action-result" and entry.get("action-attempt-id") == action_attempt_id), None)
        if existing_result is not None:
            return existing_result
        if intent.get("action-kind") == "reconcile":
            claim = recovery_claim_state(entries, now=datetime.now(timezone.utc))
            if not claim or claim.get("action-attempt-id") != action_attempt_id or claim.get("claim-generation") != resolved_generation or not claim.get("valid") or not claim.get("active") or claim.get("result") is not None:
                return {"disposition": "stale-claim", "outcome": "recovery-claim-lost", "action-attempt-id": action_attempt_id, "claim-generation": resolved_generation}
        result = _append(
            project_root,
            request_id,
            {
                "schema-version": SCHEMA_VERSION,
                "event": "action-result",
                "action-attempt-id": _text(action_attempt_id, 128),
                "claim-generation": resolved_generation,
                "outcome": _text(outcome, 128) or "unknown",
                "terminal": bool(terminal),
                "causal-input-ids": [_text(value, 128) for value in causal_input_ids if _text(value, 128)],
                "created-at": now_iso_z(),
            },
        )
    try:
        from .observability import append_observation
        append_observation(
            project_root,
            request_id,
            source="recovery-result",
            action={"event": "action-result", "kind": "recovery", "outcome": outcome, "terminal": terminal},
            causal_input_ids=[request_id, action_attempt_id],
            force_flush=bool(terminal or outcome in {"success", "completed", "provider-resume-completed", "abandon-accepted"}),
        )
    except Exception:  # noqa: BLE001 - recovery journal remains advisory
        pass
    return result


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


def classify_reconnect(record: Mapping[str, Any], *, pending_action: bool = False) -> dict[str, Any]:
    """Classify reconnect safety from durable facts without mutating state."""
    metadata = record.get("provider-metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    diagnostics = record.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    submission = metadata.get("submission-proven")
    pending = bool(pending_action or metadata.get("unresolved-turn-pending"))
    if pending or submission is True or diagnostics.get("side-effect-state") in {"may-have-started", "submission-proven", "terminal-evidence-seen"}:
        classification = "reconcile-required"
        reason = "provider-side effect may still belong to the unresolved turn"
    elif submission is False and (metadata.get("provider-session-id") or metadata.get("chat-id")):
        classification = "safe-reconnect"
        reason = "durable binding proves a provider session and submission was not started"
    elif record.get("state") in {"completed", "failed", "cancelled", "interrupted", "timed-out"}:
        classification = "terminal-observation"
        reason = "request is terminal; reconnect is observation-only"
    else:
        classification = "not-reconnectable"
        reason = "durable binding is insufficient for a safe reconnect"
    return {
        "classification": classification,
        "reason": reason,
        "read-only": True,
        "provider-binding-present": bool(metadata.get("provider-session-id") or metadata.get("chat-id")),
        "submission-proven": submission,
    }

def _cursor(offset: int, *, index_offset: int | None = None) -> str:
    payload: dict[str, int] = {"v": 1, "offset": offset}
    if index_offset is not None:
        payload["index-offset"] = index_offset
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        offset = value["offset"]
        if value.get("v") != 1 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid recovery cursor") from exc


def read_recovery_page(project_root: Path, request_id: str, *, limit: int = 25, cursor: str | None = None) -> dict[str, Any]:
    with head_read_lock(gateway_recovery_action_path(project_root, request_id)):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _PAGE_SIZE:
            raise ValueError("recovery limit must be an integer between 1 and 100")
        start = _offset(cursor)
        index_offset: int | None = None
        if cursor:
            try:
                padded = cursor + "=" * (-len(cursor) % 4)
                value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
                index_offset = value.get("index-offset")
                if index_offset is not None and (isinstance(index_offset, bool) or not isinstance(index_offset, int) or index_offset < 0):
                    raise ValueError
            except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid recovery cursor") from exc
        items: list[dict[str, Any]] = []
        has_more = False
        next_index_offset: int | None = None
        journal = gateway_recovery_action_path(project_root, request_id)
        index_path = gateway_recovery_index_path(project_root, request_id)
        if journal.exists() and index_path.exists() and not has_segments(journal):
            with index_path.open("rb") as index_handle, journal.open("rb") as journal_handle:
                if index_offset is not None:
                    index_handle.seek(index_offset)
                index = 0
                while True:
                    current_index_offset = index_handle.tell()
                    raw_index = index_handle.readline()
                    if not raw_index:
                        break
                    if index_offset is None and index < start:
                        index += 1
                        continue
                    if len(items) >= limit:
                        has_more = True
                        next_index_offset = current_index_offset
                        break
                    metadata = json.loads(raw_index)
                    journal_handle.seek(int(metadata["offset"]))
                    items.append(json.loads(journal_handle.readline().decode("utf-8")))
                    index += 1
        else:
            for index, entry in enumerate(iter_ndjson(journal)):
                if index < start:
                    continue
                if len(items) < limit:
                    items.append(entry)
                else:
                    has_more = True
                    break
        result = {
            "schema-version": SCHEMA_VERSION,
            "request-id": request_id,
            "items": items,
            "returned": len(items),
        }
        if has_more:
            result["next-cursor"] = _cursor(start + len(items), index_offset=next_index_offset)
        return result


def replay_observations(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Analyze captured journals without CDP or lifecycle mutation."""
    observation_count = 0
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"observations": 0, "errors": 0, "resolved": 0, "actions": 0, "action-success": 0})
    first_activity: int | None = None
    first_response: int | None = None
    terminal_observation = False
    response_identity_seen = False
    terminal_witness_seen = False
    completion_proven = False
    terminal_proof_seen = False
    false_terminal_observation = False
    original_errors: list[dict[str, Any]] = []
    action_outcomes: list[str] = []
    successful_action_outcomes = {
        "accepted", "completed", "success", "provider-resume-completed",
        "abandon-accepted", "reconciliation-completed", "cleared-not-submitted",
    }
    for row in entries:
        facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
        activity = facts.get("activity") if isinstance(facts, Mapping) else {}
        if first_activity is None and isinstance(activity, Mapping):
            label = activity.get("label") or activity.get("model-activity") or activity.get("activity-label")
            kind = activity.get("kind")
            if (isinstance(label, str) and is_meaningful_activity_label(label)) or kind in {
                "tool-requested", "tool-finished", "permission-requested", "in-progress",
            }:
                first_activity = int(row.get("monotonic_ms", 0))
        error = facts.get("error-occurrence") if isinstance(facts, Mapping) else {}
        error_code = "none"
        if isinstance(error, Mapping):
            error_code = next((_text(error.get(key), 128) for key in ("error-code", "failure-code", "reason-code", "code", "classification", "reason") if _text(error.get(key), 128)), "none")
        bucket = groups[error_code]
        observation_count += 1
        bucket["observations"] += 1
        if error_code != "none":
            bucket["errors"] += 1
        if isinstance(error, Mapping) and error:
            original_errors.append({
                key: error[key]
                for key in ("error-code", "failure-code", "reason-code", "code", "classification", "occurrence-id")
                if key in error
            })
        decision = facts.get("decision") if isinstance(facts, Mapping) else {}
        if isinstance(decision, Mapping) and decision.get("outcome") in {"completed", "resolved", "terminal-success"}:
            bucket["resolved"] += 1
        action = facts.get("action") if isinstance(facts, Mapping) else {}
        if isinstance(action, Mapping) and action:
            bucket["actions"] += 1
            outcome = _text(action.get("outcome"), 128)
            if outcome:
                action_outcomes.append(outcome)
            if outcome in successful_action_outcomes:
                bucket["action-success"] += 1
        response = facts.get("response-identity") if isinstance(facts, Mapping) else {}
        response = response if isinstance(response, Mapping) else {}
        is_terminal = bool(response.get("terminal") or row.get("event") == "terminal")
        has_response = bool(response.get("assistant-id") or response.get("assistant-id-hash") or response.get("response-ref-hash") or response.get("terminal-witness-present"))
        has_witness = bool(response.get("terminal-witness-present") or response.get("terminal-witness-hash"))
        terminal_observation = terminal_observation or is_terminal
        response_identity_seen = response_identity_seen or has_response
        terminal_witness_seen = terminal_witness_seen or has_witness
        if has_response and first_response is None:
            first_response = int(row.get("monotonic_ms", 0))
        if is_terminal and terminal_witness_seen and response_identity_seen:
            terminal_proof_seen = True
            completion_proven = True
    total_errors = sum(value["errors"] for value in groups.values())
    resolved = sum(value["resolved"] for value in groups.values())
    completion_proven = bool(completion_proven and terminal_observation)
    false_terminal_observation = bool(terminal_observation and not terminal_proof_seen)
    if completion_proven and total_errors:
        outcome_classification = "false-terminal-failure" if false_terminal_observation else "error-later-resolved"
    elif completion_proven:
        outcome_classification = "completed-with-witness"
    elif terminal_observation:
        outcome_classification = "terminal-without-completion-proof"
    else:
        outcome_classification = "incomplete-observation"
    return {
        "schema-version": SCHEMA_VERSION,
        "observations": observation_count,
        "groups": dict(groups),
        "resolution-rate": (resolved / total_errors) if total_errors else None,
        "first-activity-monotonic-ms": first_activity,
        "time-to-first-response-ms": (first_response - first_activity) if first_activity is not None and first_response is not None else None,
        "completion-evidence": {
            "terminal-observation-seen": terminal_observation,
            "response-identity-seen": response_identity_seen,
            "terminal-witness-seen": terminal_witness_seen,
            "completion-proven": completion_proven,
        },
        "outcome-classification": outcome_classification,
        "action-outcomes": action_outcomes[:32],
        "action-success-count": sum(1 for value in action_outcomes if value in successful_action_outcomes),
        "stop-disappearance-is-observation": True,
        "_original-errors": original_errors[:32],
    }


def replay_request(project_root: Path, request_id: str, *, observations: Iterable[Mapping[str, Any]] = (), record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Produce a deterministic, fail-closed replay decision."""
    actions = _read(project_root, request_id)
    intents = {item.get("action-attempt-id"): item for item in actions if item.get("event") == "action-intent"}
    results = {item.get("action-attempt-id") for item in actions if item.get("event") == "action-result"}
    pending = [item for key, item in intents.items() if key and key not in results]
    analysis = replay_observations(observations)
    original_errors = analysis.pop("_original-errors", [])
    reconnect = classify_reconnect(record or {}, pending_action=bool(pending))
    analysis.update({
        "request-id": request_id,
        "pending-action-attempts": [item.get("action-attempt-id") for item in pending],
        "original-errors": original_errors[:32],
        "recovery-decision": "reconciliation-required" if pending else "observation-only",
        "safe-to-resubmit": False,
        "duplicate-prompt-fence": "ambiguous-action-attempt" if pending else "no-automatic-resubmit",
        "reconnect-classification": reconnect,
    })
    return analysis


__all__ = [
    "SCHEMA_VERSION",
    "classify_reconnect",
    "prepare_recovery_action",
    "prove_turn_correlation",
    "read_recovery_page",
    "record_recovery_result",
    "replay_observations",
    "replay_request",
]
