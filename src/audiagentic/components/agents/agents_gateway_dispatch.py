"""Agent LLM Gateway provider dispatch, retry, and fallback (AG10).

The RequestRunner passed to GatewayQueueManager.enqueue. Resolves the request's
agent profile to a provider/model, dispatches through providers.services.execution
(the one allowed seam into providers — no provider-specific branches live here),
retries transient failures against the same profile, and falls back to
fallback-profile-ids only after retries on the current profile are exhausted.
Validation/config failures (unknown profile, disabled provider, invalid
request, missing model, safety/config rejection) are terminal on first
occurrence — never retried, never trigger fallback (AG10 spec + RV13).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

# Classification is code-prefix-driven (the canonical PREFIX-COMPONENT-NNN
# convention every AudiaGenticError already follows — foundation.contracts.errors
# .ERROR_CODE_PREFIXES is the exhaustive set), not a per-provider or per-message
# lookup table — config-over-code (Std 2). Covers all 11 canonical prefixes;
# no "unknown prefix" case is reachable since AudiaGenticError itself rejects
# codes outside ERROR_CODE_PREFIXES at construction time.
#
# RES ("not found, quota exceeded, rate limited") is classified terminal
# because AG10 explicitly calls out "unknown profile" (RES-AGP-001) as a
# no-fallback case; a future rate-limit-flavored RES code would currently be
# misclassified as terminal too — no adapter emits one today (rate limits
# surface as NET-*/TO-*/EXT-* in the existing adapters).
_TERMINAL_PREFIXES = ("VAL-", "RES-", "CON-", "CFG-", "VER-", "UNS-")
_TRANSIENT_PREFIXES = ("NET-", "TO-", "EXT-", "INT-", "IO-")


class _TerminalFailure(Exception):
    def __init__(self, original: AudiaGenticError) -> None:
        super().__init__(str(original))
        self.original = original


class _CancelledDuringDispatch(Exception):
    """Raised when a persisted cancel-requested flag is observed between attempts."""


def classify_failure(exc: AudiaGenticError) -> str:
    """Return 'validation_config' or 'transient' from the error's canonical code prefix.

    Unknown prefixes default to transient — retrying an unexpected failure is
    safer than silently giving up on it (worst case: one wasted retry).
    """
    for prefix in _TERMINAL_PREFIXES:
        if exc.code.startswith(prefix):
            return "validation_config"
    for prefix in _TRANSIENT_PREFIXES:
        if exc.code.startswith(prefix):
            return "transient"
    return "transient"


def _params_get(params: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in params:
            return params[key]
    return None


def resolve_retry_count(params: dict[str, Any]) -> int:
    """Resolve params.retry-count (or retry_count): additional attempts after
    the first failure, per profile. Default 1 (i.e. up to 2 total tries)."""
    value = _params_get(params, "retry-count", "retry_count")
    if value is None:
        return 1
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AudiaGenticError(
            code="VAL-AGW-030",
            kind="agents",
            message="agent profile params.retry-count must be a non-negative integer",
            details={"value": value},
        )
    return value


def _resolve_provider_disabled_error(provider_id: str) -> AudiaGenticError:
    return AudiaGenticError(
        code="VAL-AGW-031",
        kind="agents",
        message="provider is not enabled",
        details={"provider-id": provider_id},
    )


def _raise_if_cancelled(project_root: Path, request_id: str) -> None:
    """Cooperative cancellation check: subprocess/HTTP calls can't be interrupted
    mid-flight, but the retry/fallback loop can stop advancing to the next
    attempt or fallback profile once a cancel has been recorded (RV23)."""
    if store.read_record(project_root, request_id)["cancel-requested"]:
        raise _CancelledDuringDispatch()


def _extract_model_id(result: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Adapters are inconsistent about the result key (some return 'model',
    none currently return 'model-id', but normalize defensively) — fall back
    to the profile's configured model_id rather than silently losing it."""
    return result.get("model") or result.get("model-id") or profile.get("model_id")


def _build_packet_ctx(
    project_root: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    model: dict[str, Any],
) -> dict[str, Any]:
    """Build provider-neutral execution context from gateway-owned state.

    The gateway's project root is authoritative. Request metadata is correlation
    data only and cannot redirect provider execution into another directory.
    """
    return {
        "request-id": record["request-id"],
        "agent-profile-id": profile["profile_id"],
        "provider-id": profile["provider_id"],
        "model-id": model.get("model-id") or model.get("resolved"),
        "model-alias": profile.get("model_alias"),
        "prompt-body": record.get("prompt-body"),
        "params": profile.get("params", {}),
        "working-root": str(project_root.resolve()),
        "stream-controls": dict(profile.get("params", {}).get("stream-controls") or {}),
        "source": record.get("source"),
        "metadata": record.get("metadata", {}),
    }


def _dispatch_one_attempt(
    project_root: Path,
    record: dict[str, Any],
    agent_profile_id: str,
) -> dict[str, Any]:
    """Resolve profile/provider/model and call execute_provider once.

    Raises AudiaGenticError on any failure (validation or transient — caller
    classifies and decides retry/fallback). Returns the normalized provider
    result dict on success.
    """
    from audiagentic.components.agents.agents_api import resolve_profile
    from audiagentic.components.providers.services.execution import execute_provider
    from audiagentic.components.providers.services.models import resolve_model_selection
    from audiagentic.components.providers.services.provider_config import (
        is_provider_enabled,
        load_provider_config,
    )

    profile = resolve_profile(project_root, agent_profile_id)
    provider_id = profile["provider_id"]

    if not is_provider_enabled(project_root, provider_id):
        raise _resolve_provider_disabled_error(provider_id)

    provider_cfg = load_provider_config(project_root).get("providers", {}).get(provider_id, {})

    model = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_cfg,
        job_request={"model-id": profile.get("model_id"), "model-alias": profile.get("model_alias")},
    )

    packet_ctx = _build_packet_ctx(project_root, record, profile, model)
    return execute_provider(provider_id=provider_id, packet_ctx=packet_ctx, provider_cfg=provider_cfg)


def _try_profile_with_retries(
    project_root: Path,
    record: dict[str, Any],
    agent_profile_id: str,
) -> dict[str, Any]:
    """Try one profile, retrying transient failures up to its retry-count.

    Raises _TerminalFailure immediately on a validation/config error (no
    retry). Raises the last AudiaGenticError if all attempts are transient
    failures (caller decides whether to fall back to another profile).
    """
    from audiagentic.components.agents.agents_api import resolve_profile

    profile = resolve_profile(project_root, agent_profile_id)
    retry_count = resolve_retry_count(profile.get("params", {}))
    max_attempts = retry_count + 1

    last_exc: AudiaGenticError | None = None
    for attempt_num in range(max_attempts):
        _raise_if_cancelled(project_root, record["request-id"])
        started_at = now_iso_z()
        store.record_gateway_timeline(
            project_root,
            record["request-id"],
            "attempt.started",
            state=store.read_record(project_root, record["request-id"])["state"],
            attributes={
                "agent-profile-id": agent_profile_id,
                "provider-id": profile.get("provider_id"),
                "model-id": profile.get("model_id"),
                "attempt-index": attempt_num,
                "max-attempts": max_attempts,
                "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
            },
        )
        try:
            result = _dispatch_one_attempt(project_root, record, agent_profile_id)
        except AudiaGenticError as exc:
            store.append_attempt(
                project_root, record["request-id"],
                agent_profile_id=agent_profile_id,
                provider_id=profile.get("provider_id"),
                model_id=profile.get("model_id"),
                state="failed",
                error=exc,
                started_at=started_at,
                finished_at=now_iso_z(),
            )
            if classify_failure(exc) == "validation_config":
                raise _TerminalFailure(exc) from exc
            last_exc = exc
            continue
        else:
            model_id = _extract_model_id(result, profile)
            store.append_attempt(
                project_root, record["request-id"],
                agent_profile_id=agent_profile_id,
                provider_id=profile.get("provider_id"),
                model_id=model_id,
                state="completed",
                started_at=started_at,
                finished_at=now_iso_z(),
            )
            return {
                "provider-id": result.get("provider-id", profile.get("provider_id")),
                "model-id": model_id,
                "output": result.get("output"),
                "completion": result.get("completion"),
                "usage": result.get("usage"),
            }

    if last_exc is None:
        # Unreachable given max_attempts >= 1, but never trust an assert to
        # guard a production code path (asserts are stripped under -O).
        raise AudiaGenticError(
            code="INT-AGW-001",
            kind="agents",
            message="dispatch retry loop exited without a result or error",
            details={"agent-profile-id": agent_profile_id},
        )
    raise last_exc


def dispatch_request(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a queued/running gateway request record to completion.

    RequestRunner signature — passed to GatewayQueueManager.enqueue. The
    record is already 'running' when this is called (the queue manager
    transitions it before invoking the runner). Persists the terminal
    ('completed' or 'failed') state before returning.

    Cancellation is cooperative and checked only BETWEEN attempts/fallback
    candidates (_raise_if_cancelled) — an in-flight execute_provider call
    (a subprocess or HTTP request already underway) is never interrupted
    mid-flight. A cancel recorded while an attempt is running takes effect
    only once that attempt returns (RV34 finding).
    """
    candidates = [record["agent-profile-id"], *record.get("fallback-profile-ids", [])]
    last_error: AudiaGenticError | None = None

    for agent_profile_id in candidates:
        try:
            _raise_if_cancelled(project_root, record["request-id"])
            outcome = _try_profile_with_retries(project_root, record, agent_profile_id)
        except _CancelledDuringDispatch:
            return store.transition_record(project_root, record["request-id"], "cancelled")
        except _TerminalFailure as exc:
            return store.transition_record(
                project_root, record["request-id"], "failed",
                updates={"error": exc.original, "finished-at": now_iso_z()},
            )
        except AudiaGenticError as exc:
            last_error = exc
            continue
        else:
            return store.transition_record(
                project_root, record["request-id"], "completed",
                updates={**outcome, "finished-at": now_iso_z()},
            )

    if last_error is None:
        raise AudiaGenticError(
            code="INT-AGW-002",
            kind="agents",
            message="dispatch candidate loop exited without a result or error",
            details={"request-id": record["request-id"]},
        )
    return store.transition_record(
        project_root, record["request-id"], "failed",
        updates={"error": last_error, "finished-at": now_iso_z()},
    )
