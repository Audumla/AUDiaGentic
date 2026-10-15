"""Production-seam adapters for request-owned gateway observations.

These adapters consume already-normalized provider metadata, diagnostics, and
recovery outcomes. They do not inspect or control a provider session; the
observation journal remains a passive evidence sink.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.diagnostics import activity_group, normalize_activity_label
from audiagentic.foundation.transports.agent_session import TransportObservationKind
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


_DIAGNOSTIC_GATE_KEYS = frozenset({
    "composer-present", "composer-editable", "composer-unavailable", "generating",
    "raw-generating", "not-generating", "completion-satisfied", "completion-control",
    "more-actions-menu", "response-complete-status", "terminal-witness-present",
    "terminal-witness-is-latest", "terminal-witness-is-response", "prompt-ref-present",
    "response-ref-present", "response-ref-is-latest", "response-ref-is-bound",
    "raw-same-bound-conversation", "raw-matches-provider-session", "prompt-unmounted",
})
_CORRELATION_KEYS = frozenset({
    "page-handle-digest", "raw-url-digest", "baseline-url-digest", "bound-url-digest",
    "correlation-error", "response-ref-present", "response-ref-is-latest",
    "response-ref-is-bound", "terminal-witness-present", "terminal-witness-is-latest",
    "terminal-witness-is-response", "prompt-ref-present", "raw-matches-provider-session",
})


def _bounded_text(value: Any, limit: int = 256) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _digest(value: Any) -> str | None:
    text = _bounded_text(value, 512)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32] if text else None


def _diagnostic_details(attributes: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = attributes.get("diagnostic-details")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16 * 1024:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def project_transport_observation(observation: Any) -> dict[str, Any]:
    """Project one TransportObservation into shared bounded diagnostic facts."""
    attributes = observation.attributes if isinstance(getattr(observation, "attributes", None), Mapping) else {}
    kind = getattr(getattr(observation, "kind", None), "value", None) or str(getattr(observation, "kind", "unknown"))
    facts = _diagnostic_details(attributes)
    activity_label = _bounded_text(attributes.get("model_activity"), 64)
    activity_label = normalize_activity_label(activity_label) if activity_label else None
    activity: dict[str, Any] = {"kind": kind}
    correlation_quality = _bounded_text(attributes.get("correlation-quality"), 64)
    if correlation_quality:
        activity["correlation-quality"] = correlation_quality
    if activity_label:
        activity["label"] = activity_label
        group = activity_group(activity_label)
        if group:
            activity["group"] = group
    diagnostic: dict[str, Any] = {}
    dom_signals: dict[str, bool | int] = {}
    raw_signals = facts.get("scoped-dom-signals") or facts.get("raw-dom-signals") or facts.get("dom-signals")
    if isinstance(raw_signals, (list, tuple, set, frozenset)):
        normalized = {str(value).strip().lower().replace("_", "-") for value in raw_signals if isinstance(value, str) and value.strip()}
        dom_signals.update({signal: True for signal in sorted(normalized & _DOM_SIGNALS)})
        dom_signals["signal-count"] = len(normalized)
    for key in _DIAGNOSTIC_GATE_KEYS:
        value = facts.get(key)
        if isinstance(value, bool):
            diagnostic[key] = value
    completion_gates = facts.get("completion-gates")
    if isinstance(completion_gates, Mapping):
        diagnostic["completion-gates"] = {
            str(key)[:64]: bool(value)
            for key, value in list(completion_gates.items())[:32]
            if isinstance(value, bool)
        }
    matched = facts.get("completion-matched")
    if isinstance(matched, (list, tuple)):
        diagnostic["completion-matched"] = [str(value)[:64] for value in matched if isinstance(value, str)][:16]
    response_identity: dict[str, Any] = {}
    for key in ("terminal-witness-hash", "response-ref-hash", "latest-assistant-hash"):
        if (value := _bounded_text(facts.get(key), 128)):
            response_identity[key] = value
    if kind == TransportObservationKind.TERMINAL.value:
        response_identity["terminal"] = True
        for key in ("stop_reason", "stop-reason"):
            if (value := _bounded_text(attributes.get(key))):
                response_identity["stop-reason"] = value
                break
    for key in ("terminal-witness-id", "terminal-witness-assistant-id", "latest-assistant-id", "response-ref-id"):
        if (value := _digest(facts.get(key))):
            response_identity[key.replace("_", "-") + "-hash"] = value
    if diagnostic.get("terminal-witness-present"):
        response_identity["terminal-witness-present"] = True
    error_occurrence: dict[str, Any] = {}
    for key in ("error_code", "error-code", "reason", "failure-code", "classification", "correlation-error"):
        if (value := _bounded_text(attributes.get(key) or facts.get(key))):
            error_occurrence[key.replace("_", "-")] = value
    decision: dict[str, Any] = {}
    for key in ("completion-satisfied", "not-generating", "composer-editable", "raw-same-bound-conversation", "raw-matches-provider-session"):
        if key in diagnostic:
            decision[key] = diagnostic[key]
    for key in ("timing-event", "diagnostic-signature"):
        value = _bounded_text(attributes.get(key) or facts.get(key), 128)
        if value:
            decision[key] = value
    correlation = {key: facts[key] for key in _CORRELATION_KEYS if key in facts and isinstance(facts[key], (str, bool))}
    if correlation:
        decision["correlation"] = correlation
    return {
        "activity": activity,
        "dom-signals": dom_signals,
        "diagnostic-facts": diagnostic,
        "response-identity": response_identity,
        "error-occurrence": error_occurrence,
        "decision": decision,
        "controls": {key.replace("_", "-"): attributes[key] for key in ("tool_call_id", "tool_status") if isinstance(attributes.get(key), (str, int, bool))},
        "correlation": correlation,
    }


def append_transport_observation(
    project_root: Path,
    request_id: str,
    observation: Any,
    *,
    session_id: str | None = None,
    source: str = "session-transport",
    cdp_target_hash: str | None = None,
    attempt_epoch: int = 1,
    force_flush: bool = False,
) -> dict[str, Any]:
    """Persist the shared bounded TransportObservation projection for GA03."""
    projected = project_transport_observation(observation)
    kind = getattr(getattr(observation, "kind", None), "value", None) or str(getattr(observation, "kind", "unknown"))
    return append_observation(
        project_root,
        request_id,
        session_id=session_id,
        turn_id=getattr(observation, "turn_id", None),
        cdp_target_hash=cdp_target_hash,
        attempt_epoch=attempt_epoch,
        poll_seq=int(getattr(observation, "sequence", None) or 0),
        source=source,
        dom_signals=projected["dom-signals"],
        activity=projected["activity"],
        controls=projected["controls"],
        response_identity=projected["response-identity"],
        error_occurrence=projected["error-occurrence"],
        decision=projected["decision"],
        action={"kind": kind} if kind in {"tool-requested", "permission-requested"} else {},
        causal_input_ids=[request_id, session_id or ""],
        force_flush=force_flush or kind in {"terminal", "transport-error", "transport-closed"},
        observed_at=getattr(observation, "observed_at", None),
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
        force_flush=record.get("state") in {"completed", "failed", "cancelled", "interrupted", "timed-out"},
    )


__all__ = ["append_request_projection", "append_transport_observation", "project_transport_observation"]
