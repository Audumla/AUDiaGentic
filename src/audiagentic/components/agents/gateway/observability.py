"""Durable, redacted request-owned observation journals (GA03).

The journal is deliberately independent from provider adapters. Producers may
submit normalized facts, but this boundary never persists raw DOM, prompts,
responses, cookies, storage, headers, tokens, or network bodies. A request
mutation lock gives event sequence assignment and append ordering the same
cross-process fence as lifecycle mutations.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

from audiagentic.components.agents.agents_paths import (
    gateway_observation_artifact_dir,
    gateway_observation_path,
    gateway_request_path,
)
from audiagentic.foundation.io import iter_ndjson, last_ndjson
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z

SCHEMA_VERSION = "gateway-observation.v1"
ARTIFACT_SCHEMA_VERSION = "gateway-observation-artifact.v1"
_MAX_TEXT = 256
_MAX_ITEMS = 32
_MAX_DOM_DECOMPRESSED = 256 * 1024
_MAX_DOM_COMPRESSED = 64 * 1024
_SENSITIVE = re.compile(
    r"(?:cookie|storage|authorization|header|token|secret|password|credential|network|body|"
    r"prompt|raw[-_ ]?dom|response[-_ ]?text|access[-_ ]?token|message|description|value|content|html|text|input|query|url)",
    re.IGNORECASE,
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any, limit: int = _MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:limit] if cleaned else None


_SAFE_TEXT_KEYS = frozenset(
    {
        "id", "kind", "state", "status", "phase", "label", "event", "source",
        "code", "classification", "outcome", "digest", "hash", "sequence", "count",
        "model-activity", "tool-call-id", "tool-status", "stop-reason",
        "error-code", "reason", "timing-event", "diagnostic-signature",
        "correlation-quality", "assistant-id", "turn-id",
    }
)


def _safe(value: Any, *, depth: int = 0) -> Any:
    """Project provider facts to bounded JSON without secret-bearing keys."""
    if depth > 3:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:_MAX_ITEMS]:
            key = _text(raw_key, 64)
            if not key or _SENSITIVE.search(key):
                continue
            projected = _safe(raw_value, depth=depth + 1)
            normalized_key = key.casefold().replace("_", "-")
            if isinstance(projected, str) and normalized_key not in _SAFE_TEXT_KEYS:
                continue
            if projected is not None:
                result[key] = projected
        return result
    if isinstance(value, (list, tuple)):
        return [
            item
            for item in (
                None if isinstance(v, str) else _safe(v, depth=depth + 1)
                for v in value[:_MAX_ITEMS]
            )
            if item is not None
        ]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return _text(value)

def _project_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    projected = _safe(fields or {})
    return projected if isinstance(projected, dict) else {}


def _cursor(value: int) -> str:
    raw = json.dumps({"event_seq": value}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> int:
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        sequence = decoded["event_seq"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError
        return sequence
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("invalid observation cursor") from None


def _journal_lock(project_root: Path, request_id: str) -> StartupLock:
    return StartupLock(gateway_request_path(project_root, request_id).with_name("mutation.lock"))


def _changed_fields(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[str]:
    if not previous:
        return sorted(current)
    return sorted(key for key in current if previous.get(key) != current.get(key))


def append_observation(
    project_root: Path,
    request_id: str,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
    project_hash: str | None = None,
    cdp_target_hash: str | None = None,
    attempt_epoch: int = 1,
    poll_seq: int = 0,
    source: str = "gateway",
    dom_signals: Mapping[str, Any] | None = None,
    activity: Mapping[str, Any] | None = None,
    controls: Mapping[str, Any] | None = None,
    response_identity: Mapping[str, Any] | None = None,
    error_occurrence: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
    action: Mapping[str, Any] | None = None,
    causal_input_ids: list[str] | tuple[str, ...] | None = None,
    policy_config_digest: str | None = None,
    producer_version: str = "audiagentic",
    build_version: str = "unknown",
    observed_at: str | None = None,
    monotonic_ms: int | None = None,
) -> dict[str, Any]:
    """Append one immutable observation, coalescing identical polls safely."""
    safe_parts = {
        "dom-signals": _project_fields(dom_signals),
        "activity": _project_fields(activity),
        "controls": _project_fields(controls),
        "response-identity": _project_fields(response_identity),
        "error-occurrence": _project_fields(error_occurrence),
        "decision": _project_fields(decision),
        "action": _project_fields(action),
    }
    current_digest = _digest(safe_parts)
    journal_path = gateway_observation_path(project_root, request_id)
    with _journal_lock(project_root, request_id):
        previous = last_ndjson(journal_path)
        event_seq = int(previous.get("event_seq", 0)) + 1 if previous else 1
        previous_digest = previous.get("current_digest") if previous else None
        unchanged = bool(
            previous
            and previous_digest == current_digest
            and previous.get("event") in {"dom-observed", "observation-coalesced"}
        )
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event": "observation-coalesced" if unchanged else "dom-observed",
            "event_id": f"obs_{request_id}_{event_seq}",
            "event_seq": event_seq,
            "attempt_epoch": max(1, int(attempt_epoch)),
            "poll_seq": max(0, int(poll_seq)),
            "observed_at": observed_at or now_iso_z(),
            "monotonic_ms": int(monotonic_ms if monotonic_ms is not None else time.monotonic() * 1000),
            "producer_version": _text(producer_version, 64) or "unknown",
            "build_version": _text(build_version, 128) or "unknown",
            "policy_config_digest": _text(policy_config_digest, 128),
            "project_hash": _text(project_hash, 128) or _digest(str(project_root))[:32],
            "session_id": _text(session_id, 128),
            "request_id": _text(request_id, 128),
            "turn_id": _text(turn_id, 128),
            "cdp_target_hash": _text(cdp_target_hash, 128),
            "source": _text(source, 64) or "gateway",
            "previous_digest": previous_digest,
            "current_digest": current_digest,
            "changed_fields": _changed_fields(previous.get("facts") if previous else None, safe_parts),
            "causal_input_ids": [_text(item, 128) for item in (causal_input_ids or []) if _text(item, 128)],
            "facts": safe_parts,
        }
        if unchanged:
            prior = previous.get("coalesced") if isinstance(previous.get("coalesced"), dict) else {}
            first_seq = int(prior.get("first_event_seq", previous.get("event_seq", event_seq)))
            first_poll = int(prior.get("first_poll_seq", previous.get("poll_seq", poll_seq)))
            previous_mono = int(previous.get("monotonic_ms", event["monotonic_ms"]))
            poll_gap = max(1, event["poll_seq"] - int(previous.get("poll_seq", first_poll)))
            event["coalesced"] = {
                "first_event_seq": first_seq,
                "last_event_seq": event_seq,
                "repeat_count": int(prior.get("repeat_count", 1)) + poll_gap,
                "first_poll_seq": first_poll,
                "last_poll_seq": event["poll_seq"],
                "max_gap_ms": max(int(prior.get("max_gap_ms", 0)), max(0, event["monotonic_ms"] - previous_mono)),
            }
        if unchanged and previous and previous.get("event") == "observation-coalesced":
            poll_gap = max(0, event["poll_seq"] - int(previous.get("poll_seq", 0)))
            if poll_gap < 8:
                event["event_seq"] = int(previous.get("event_seq", event_seq))
                event["event_id"] = str(previous.get("event_id") or event["event_id"])
                event["coalesced"]["last_event_seq"] = event["event_seq"]
                event["coalesced"]["repeat_count"] = int(previous.get("coalesced", {}).get("repeat_count", 1)) + poll_gap
                return event
        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    return event


def read_observation_page(
    project_root: Path,
    request_id: str,
    *,
    limit: int = 25,
    cursor: str | None = None,
    since_sequence: int | None = None,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("observation limit must be an integer between 1 and 100")
    after = max(_decode_cursor(cursor), int(since_sequence or 0))
    page: list[dict[str, Any]] = []
    has_more = False
    for item in iter_ndjson(gateway_observation_path(project_root, request_id)):
        if int(item.get("event_seq", 0)) <= after:
            continue
        if len(page) < limit:
            page.append(item)
        else:
            has_more = True
            break
    next_cursor = _cursor(int(page[-1]["event_seq"])) if has_more and page else None
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "items": page,
        "count": len(page),
        "has_more": bool(next_cursor),
        "next_cursor": next_cursor,
    }


def observation_summary(project_root: Path, request_id: str) -> dict[str, Any]:
    count = 0
    first = None
    latest = None
    for item in iter_ndjson(gateway_observation_path(project_root, request_id)):
        count += 1
        first = first or item
        latest = item
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "count": count,
        "first_event_seq": first.get("event_seq") if first else None,
        "last_event_seq": latest.get("event_seq") if latest else None,
        "last_poll_seq": latest.get("poll_seq") if latest else None,
        "latest": latest,
    }


def capture_redacted_artifact(
    project_root: Path,
    request_id: str,
    value: Mapping[str, Any],
    *,
    ttl_seconds: int = 3600,
    max_compressed_bytes: int = _MAX_DOM_COMPRESSED,
    max_decompressed_bytes: int = _MAX_DOM_DECOMPRESSED,
) -> dict[str, Any]:
    """Persist an explicitly requested bounded redacted DOM/accessibility artifact."""
    safe = _safe(value)
    raw = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > min(max_decompressed_bytes, _MAX_DOM_DECOMPRESSED):
        raise ValueError("observation artifact exceeds decompressed size cap")
    compressed = gzip.compress(raw, mtime=0)
    if len(compressed) > min(max_compressed_bytes, _MAX_DOM_COMPRESSED):
        raise ValueError("observation artifact exceeds compressed size cap")
    digest = hashlib.sha256(compressed).hexdigest()
    directory = gateway_observation_artifact_dir(project_root, request_id)
    path = directory / f"{digest}.json.gz"
    with _journal_lock(project_root, request_id):
        directory.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(compressed)
        manifest = directory / "manifest.ndjson"
        metadata = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_id": digest,
            "media_type": "application/json+gzip",
            "compressed_bytes": len(compressed),
            "decompressed_bytes": len(raw),
            "created_at": now_iso_z(),
            "expires_at_epoch": int(time.time()) + max(1, int(ttl_seconds)),
        }
        with manifest.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return metadata


def purge_observation_artifacts(project_root: Path, request_id: str) -> int:
    """Purge request-owned optional artifacts; request-directory purge also removes them."""
    directory = gateway_observation_artifact_dir(project_root, request_id)
    removed = 0
    if not directory.exists():
        return 0
    for path in directory.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
    directory.rmdir()
    return removed


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "append_observation",
    "capture_redacted_artifact",
    "observation_summary",
    "purge_observation_artifacts",
    "read_observation_page",
]
