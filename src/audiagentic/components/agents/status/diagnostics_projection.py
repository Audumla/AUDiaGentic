"""AS102 public diagnostics boundary.

GP48 owns the meaning of diagnostic fields.  This module owns only the public
shape, redaction, and deterministic bounds; it never classifies a failure.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from audiagentic.foundation.logging.redaction import redact_text

MAX_DIAGNOSTICS_BYTES = 16 * 1024
MAX_EVIDENCE_ITEMS = 100
_MAX_TEXT = 256
_PATH_OR_URI = re.compile(r"(?i)(?:file://|[a-z]:[\\/]|/(?:Users|home|tmp|var)/)")

_ROLLUP_FIELDS = (
    "version", "classification", "certainty", "phase", "side-effect-state",
    "resolution-state", "failure-code", "reason-code", "evidence-count",
    "coalesced-observation-count",
)
_RECOVERY_FIELDS = ("disposition", "allowed-actions")
_EVIDENCE_FIELDS = (
    "evidence-id", "sequence", "request-id", "session-id", "attempt-epoch",
    "phase", "kind", "certainty", "side-effect-state", "source",
    "source-sequence", "observed-at",
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = redact_text(str(value))
    if _PATH_OR_URI.search(text):
        return "[REDACTED]"
    return text[:_MAX_TEXT]


def _scalar(value: Any) -> Any:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    return _text(value)


def _rollup(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for field in _ROLLUP_FIELDS:
        if field in value:
            result[field] = _scalar(value[field])
    recovery = value.get("recovery")
    if isinstance(recovery, Mapping):
        result["recovery"] = {
            "disposition": _text(recovery.get("disposition")),
            "allowed-actions": [
                item for item in (_text(raw) for raw in recovery.get("allowed-actions", ()))
                if item is not None
            ][:20],
        }
    signals = value.get("provider-signals")
    if isinstance(signals, Sequence) and not isinstance(signals, (str, bytes, bytearray)):
        result["provider-signals"] = [
            item for item in (_text(raw) for raw in signals) if item is not None
        ][:20]
    return result


def _evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {field: _scalar(value[field]) for field in _EVIDENCE_FIELDS if field in value}


def _monitoring(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    fields = (
        "activity-sequence", "started-at", "first-activity-at",
        "first-activity-latency-seconds", "no-activity-seconds", "watcher-state",
    )
    return {field: _scalar(value[field]) for field in fields if field in value}


def project_public_diagnostics(
    payload: Mapping[str, Any],
    *,
    max_bytes: int = MAX_DIAGNOSTICS_BYTES,
) -> dict[str, Any]:
    """Return a closed, redacted, deterministically bounded diagnostics shape."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1024:
        max_bytes = MAX_DIAGNOSTICS_BYTES
    raw_evidence = payload.get("evidence")
    evidence = [_evidence(item) for item in raw_evidence] if isinstance(raw_evidence, list) else []
    result: dict[str, Any] = {
        "request-id": _text(payload.get("request-id")),
        "session-id": _text(payload.get("session-id")),
        "state": _text(payload.get("state")),
        "diagnostics": _rollup(payload.get("diagnostics")),
        "monitoring": _monitoring(payload.get("monitoring")),
        "evidence": evidence[-MAX_EVIDENCE_ITEMS:],
        "latest-transition": None,
        "truncated": False,
    }
    transition = payload.get("latest-transition")
    if isinstance(transition, Mapping):
        result["latest-transition"] = {
            "event": _text(transition.get("event")),
            "state": _text(transition.get("state")),
            "timestamp": _text(transition.get("timestamp")),
        }

    def encoded_size() -> int:
        return len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    while encoded_size() > max_bytes and result["evidence"]:
        result["evidence"].pop(0)
        result["truncated"] = True
    if encoded_size() > max_bytes:
        result["diagnostics"] = None
        result["latest-transition"] = None
        result["truncated"] = True
    return result


__all__ = ["MAX_DIAGNOSTICS_BYTES", "project_public_diagnostics"]
