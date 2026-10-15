"""Production-seam adapters for request-owned gateway observations.

These adapters consume already-normalized provider metadata, diagnostics, and
recovery outcomes. They do not inspect or control a provider session; the
observation journal remains a passive evidence sink.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .observability import append_observation

_DOM_SIGNALS = frozenset(
    {
        "completion-control",
        "response-complete",
        "response-complete-status",
        "stop-control",
        "more-actions-menu",
        "provider-interruption",
        "error-alert",
        "request-error-alert",
        "stream-cache-expired",
        "conversation-load-failed",
        "auth-required",
        "rate-limit",
        "delivery-timeout-alert",
        "delivery-timeout-retry",
    }
)


def _hash(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _signals(metadata: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> dict[str, bool | int]:
    raw: list[Any] = []
    for source in (metadata, diagnostics):
        for key in ("dom-signals", "observed-dom-signals", "scoped-dom-signals", "provider-signals"):
            value = source.get(key)
            if isinstance(value, (list, tuple, set, frozenset)):
                raw.extend(value)
    normalized = {
        str(value).strip().lower().replace("_", "-")
        for value in raw
        if isinstance(value, str) and value.strip()
    }
    result: dict[str, bool | int] = {signal: True for signal in sorted(normalized & _DOM_SIGNALS)}
    result["signal-count"] = len(normalized)
    return result


def append_request_projection(
    project_root: Path,
    request_id: str,
    record: Mapping[str, Any],
    *,
    source: str = "gateway-request",
    action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project real binding/diagnostic/decision metadata into the journal."""
    metadata = record.get("provider-metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    diagnostics = record.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    activity = record.get("activity")
    activity = activity if isinstance(activity, Mapping) else {}
    assistant_id = metadata.get("assistant-message-id") or metadata.get("observed-assistant-id")
    terminal_evidence = metadata.get("terminal-evidence")
    terminal = bool(terminal_evidence) or record.get("state") in {
        "completed", "failed", "cancelled", "interrupted", "timed-out"
    }
    response_identity: dict[str, Any] = {
        "terminal": terminal,
        "identity-quality": "provider-bound" if assistant_id else "request-scoped",
    }
    if isinstance(assistant_id, str) and assistant_id:
        response_identity["assistant-id"] = assistant_id
    if isinstance(terminal_evidence, Mapping):
        stop_reason = terminal_evidence.get("stop-reason") or terminal_evidence.get("stop_reason")
        if isinstance(stop_reason, str) and stop_reason:
            response_identity["stop-reason"] = stop_reason
    error_occurrence = {
        key: diagnostics.get(key)
        for key in ("failure-code", "reason-code", "classification")
        if isinstance(diagnostics.get(key), str) and diagnostics.get(key)
    }
    side_effect = diagnostics.get("side-effect-state")
    decision = {
        "side-effect-state": side_effect,
        "resolution-state": diagnostics.get("resolution-state"),
        "submission-proven": metadata.get("submission-proven"),
        "submission-ambiguous": metadata.get("submission-ambiguous"),
        "binding-present": bool(metadata.get("provider-session-id") or metadata.get("chat-id")),
        "turn-bound": bool(metadata.get("unresolved-turn-id") or record.get("turn-id")),
    }
    if diagnostics.get("recovery") and isinstance(diagnostics["recovery"], Mapping):
        decision["reconnect-classification"] = diagnostics["recovery"].get("disposition")
    chat_id = metadata.get("provider-session-id") or metadata.get("chat-id")
    target_id = metadata.get("target-id") or metadata.get("cdp-target-id")
    return append_observation(
        project_root,
        request_id,
        session_id=record.get("session-id") if isinstance(record.get("session-id"), str) else None,
        turn_id=record.get("turn-id") if isinstance(record.get("turn-id"), str) else None,
        cdp_target_hash=_hash(target_id or chat_id),
        attempt_epoch=int(record.get("attempt-epoch") or 1),
        poll_seq=int(activity.get("sequence") or record.get("activity-sequence") or 0),
        source=source,
        dom_signals=_signals(metadata, diagnostics),
        activity={
            "label": activity.get("provider") or activity.get("source") or metadata.get("activity-label"),
            "sequence": activity.get("sequence") or record.get("activity-sequence"),
        },
        response_identity=response_identity,
        error_occurrence=error_occurrence,
        decision=decision,
        action=action or {},
        causal_input_ids=[request_id, str(record.get("session-id") or "")],
    )


__all__ = ["append_request_projection"]
