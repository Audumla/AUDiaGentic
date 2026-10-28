"""Safe rolling retention and bounded gateway journal compaction.

Rolling retention never deletes request directories. It reduces the number of
full-resolution terminal histories that remain eligible for detailed journal
retention, while per-journal compaction preserves terminal evidence and rebuilds
the byte index atomically.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_observation_index_path,
    gateway_observation_path,
    gateway_recovery_action_path,
    gateway_recovery_index_path,
    gateway_request_dir,
    gateway_root,
    gateway_timeline_index_path,
    gateway_timeline_path,
)
from audiagentic.components.agents.gateway.operations.retention_policy import (
    DEFAULT_CONSOLE_TRACE_MAX_BYTES,
    DEFAULT_OBSERVATION_MAX_BYTES,
    DEFAULT_RECOVERY_MAX_BYTES,
    DEFAULT_REQUEST_HISTORY_LIMIT,
    DEFAULT_TIMELINE_MAX_BYTES,
    load_retention_policy,
)
from audiagentic.components.agents.gateway.session.retention import request_retention_pin
from audiagentic.foundation.observability.journal_segments import compact_indexed_ndjson
from audiagentic.foundation.system.process import StartupLock

logger = logging.getLogger(__name__)

_RETENTION_SCHEDULER_LOCK = threading.Lock()
_RETENTION_PENDING: dict[str, tuple[Path, str | None]] = {}
_RETENTION_WORKER_RUNNING = False

_MAX_ENV_BYTES = 256 * 1024 * 1024
_TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "rejected", "interrupted", "timed-out", "expired", "abandoned"}
)
_JOURNAL_SPECS = {
    "timeline": (gateway_timeline_path, gateway_timeline_index_path, DEFAULT_TIMELINE_MAX_BYTES),
    "observation": (gateway_observation_path, gateway_observation_index_path, DEFAULT_OBSERVATION_MAX_BYTES),
    "recovery": (gateway_recovery_action_path, gateway_recovery_index_path, DEFAULT_RECOVERY_MAX_BYTES),
}


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, _MAX_ENV_BYTES))


def request_retention_count() -> int:
    """Return the configured number of full-resolution terminal histories."""
    return _env_positive_int(
        "AUDIAGENTIC_GATEWAY_REQUEST_RETENTION_COUNT",
        load_retention_policy().request_history_limit or DEFAULT_REQUEST_HISTORY_LIMIT,
    )


def journal_max_bytes(kind: str) -> int:
    """Return the bounded byte cap for one request-owned journal."""
    policy = load_retention_policy()
    configured = {
        "timeline": policy.timeline_max_bytes,
        "observation": policy.observation_max_bytes,
        "recovery": policy.recovery_max_bytes,
    }.get(kind)
    if configured is None:
        raise ValueError(f"unknown gateway journal kind: {kind}")
    return _env_positive_int(f"AUDIAGENTIC_GATEWAY_{kind.upper()}_MAX_BYTES", configured)


def console_trace_max_bytes() -> int:
    return _env_positive_int(
        "AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_MAX_BYTES",
        load_retention_policy().console_trace_max_bytes or DEFAULT_CONSOLE_TRACE_MAX_BYTES,
    )


def _terminal_timeline(row: dict[str, Any]) -> bool:
    return row.get("state") in _TERMINAL_STATES


def _terminal_observation(row: dict[str, Any]) -> bool:
    facts = row.get("facts")
    if not isinstance(facts, dict):
        return False
    for section in facts.values():
        if not isinstance(section, dict):
            continue
        if section.get("terminal") is True or section.get("terminal-witness") is True:
            return True
        if section.get("resolution-state") in {"resolved", "unresolved", "reconciliation-requested"}:
            return True
        if section.get("outcome") in _TERMINAL_STATES or section.get("state") in _TERMINAL_STATES:
            return True
    return False


def _terminal_recovery(row: dict[str, Any]) -> bool:
    return row.get("event") in {"action-result", "recovery-terminal", "reconciliation-result"}


def compact_request_journals(project_root: Path, request_id: str) -> int:
    """Compact all three request journals under the request mutation fence."""
    changed = 0
    with StartupLock(gateway_request_dir(project_root, request_id) / "mutation.lock"):
        for kind, (journal_fn, index_fn, default) in _JOURNAL_SPECS.items():
            journal_path = journal_fn(project_root, request_id)
            index_path = index_fn(project_root, request_id)
            if not journal_path.exists():
                continue
            # Rotated journals are append-only. Their daily segments are
            # maintained by age, independently of the historical count cap.
            if journal_path.with_name(journal_path.name + ".rotation.json").exists():
                continue
            try:
                maximum = journal_max_bytes(kind)
                predicate = {
                    "timeline": _terminal_timeline,
                    "observation": _terminal_observation,
                    "recovery": _terminal_recovery,
                }[kind]
                changed += int(
                    compact_indexed_ndjson(
                        journal_path,
                        index_path,
                        max_bytes=maximum,
                        preserve=predicate,
                    )
                )
            except (OSError, ValueError, TypeError):
                logger.warning("gateway journal compaction failed", extra={"request-id": request_id, "kind": kind}, exc_info=True)
    return changed


def _sort_key(record: dict[str, Any], path: Path) -> tuple[datetime, str]:
    value = record.get("finished-at") or record.get("updated-at") or record.get("created-at")
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OSError):
        timestamp = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    if timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()
    return timestamp, str(record.get("request-id") or path.name)


def _eligible_record(
    project_root: Path, entry: Path, *, positive_lineage: frozenset[str] = frozenset(),
    retention_fence_held: bool = False,
) -> tuple[dict[str, Any], tuple[datetime, str]] | None:
    record_path = entry / "record.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("state") not in _TERMINAL_STATES:
        return None
    if record.get("recovery-required") is True:
        return None
    if record.get("terminal-finalization"):
        return None
    diagnostics = record.get("diagnostics")
    if isinstance(diagnostics, dict) and diagnostics.get("resolution-state") in {"unresolved", "reconciliation-requested"}:
        return None
    request_id = record.get("request-id")
    if not isinstance(request_id, str) or request_id != entry.name:
        return None
    if request_id in positive_lineage:
        return None
    try:
        # Positive runtime protection is sufficient to keep the request.
        # Most admitted records retain their private prompt here; scanning
        # every session under the global pin lock first is unnecessary.
        # A disappearing root can only conservatively defer one sweep.
        runtime_root = entry / "runtime"
        if runtime_root.is_dir() and next(runtime_root.iterdir(), None) is not None:
            return None
        pin = request_retention_pin
        if retention_fence_held:
            from .session.retention import _request_retention_pin_unlocked
            pin = _request_retention_pin_unlocked
        if pin(project_root, request_id).pinned:
            return None
    except (OSError, ValueError, TypeError):
        return None
    return record, _sort_key(record, record_path)


def enforce_request_retention(project_root: Path, *, exclude_request_id: str | None = None) -> dict[str, int]:
    """Compact older resolved histories without deleting any request directory."""
    root = gateway_root(project_root)
    result = {
        "limit": request_retention_count(),
        "eligible": 0,
        "retained": 0,
        "compacted": 0,
        "protected": 0,
    }
    if not root.exists():
        return result
    from .session.retention import positive_session_lineage_snapshot

    try:
        positive_lineage = positive_session_lineage_snapshot(project_root)
    except Exception:  # noqa: BLE001 - failed maintenance census must not change eligibility
        logger.warning("gateway retention skipped after failed lineage census", exc_info=True)
        return result
    eligible: list[tuple[tuple[datetime, str], str]] = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name in {"idempotency", "sessions", "archive", "maintenance-locks"}:
            continue
        candidate = _eligible_record(project_root, entry, positive_lineage=positive_lineage)
        if candidate is None:
            result["protected"] += 1
            continue
        record, key = candidate
        if record.get("request-id") == exclude_request_id:
            result["retained"] += 1
            continue
        eligible.append((key, str(record["request-id"])))
    eligible.sort()
    result["eligible"] = len(eligible)
    result["retained"] = min(result["eligible"], result["limit"])
    for _, request_id in eligible[:-result["limit"]] if result["limit"] else eligible:
        result["compacted"] += compact_request_journals(project_root, request_id)
    return result


def schedule_request_retention(
    project_root: Path, *, trigger_request_id: str | None = None
) -> bool:
    """Queue a coalesced retention sweep without delaying request terminalization.

    Terminal transitions are on the provider response path. A large legacy
    backlog can make compaction take minutes, so it must never run inline while
    the request mutation lock is held. One daemon worker drains one pending
    sweep per project; additional terminal transitions coalesce into a follow-
    up pass.
    """
    global _RETENTION_WORKER_RUNNING

    root = project_root.resolve()
    key = str(root)
    with _RETENTION_SCHEDULER_LOCK:
        _RETENTION_PENDING[key] = (root, trigger_request_id)
        if _RETENTION_WORKER_RUNNING:
            return True
        _RETENTION_WORKER_RUNNING = True
    try:
        threading.Thread(
            target=_drain_request_retention,
            name="gateway-request-retention",
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001 - compaction cannot block terminal state
        with _RETENTION_SCHEDULER_LOCK:
            _RETENTION_WORKER_RUNNING = False
        logger.exception("could not start gateway request-retention worker")
        return False
    return True


def _drain_request_retention() -> None:
    global _RETENTION_WORKER_RUNNING

    while True:
        with _RETENTION_SCHEDULER_LOCK:
            if not _RETENTION_PENDING:
                _RETENTION_WORKER_RUNNING = False
                return
            key = sorted(_RETENTION_PENDING)[0]
            project_root, trigger_request_id = _RETENTION_PENDING.pop(key)

        started = time.perf_counter()
        summary: dict[str, int] | None = None
        error: Exception | None = None
        try:
            summary = enforce_request_retention(project_root)
            from .journal_retention import maintain_project_journals
            summary.update(maintain_project_journals(project_root))
        except Exception as exc:  # noqa: BLE001 - later terminal events can retry
            error = exc
            logger.exception(
                "gateway request-retention sweep failed",
                extra={"trigger-request-id": trigger_request_id},
            )
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        if trigger_request_id:
            try:
                from audiagentic.components.agents.agents_paths import (
                    gateway_request_maintenance_lock_path,
                    gateway_request_path,
                )
                from audiagentic.components.agents.gateway.observability import (
                    append_observation,
                )

                # Purge and maintenance share an external fence. A completed sweep
                # must not recreate a request removed while the worker ran.
                with StartupLock(gateway_request_maintenance_lock_path(project_root, trigger_request_id)):
                    if not gateway_request_path(project_root, trigger_request_id).is_file():
                        continue
                    append_observation(
                        project_root,
                        trigger_request_id,
                        source="request-retention",
                        diagnostic_facts={
                            "retention": {
                                "sweep-duration-ms": duration_ms,
                                "sweep-result": summary,
                                "error-kind": type(error).__name__ if error else None,
                            }
                        },
                        decision={"maintenance-is-asynchronous": True},
                        action={
                            "event": "request-retention-sweep",
                            "kind": "retention-maintenance",
                            "outcome": "failed" if error else "completed",
                        },
                        causal_input_ids=[trigger_request_id],
                        force_flush=True,
                    )
            except Exception:  # noqa: BLE001 - tracing cannot affect request state
                logger.debug(
                    "could not append gateway retention observation",
                    extra={"trigger-request-id": trigger_request_id},
                    exc_info=True,
                )


__all__ = [
    "compact_indexed_ndjson",
    "compact_request_journals",
    "console_trace_max_bytes",
    "enforce_request_retention",
    "journal_max_bytes",
    "request_retention_count",
]
