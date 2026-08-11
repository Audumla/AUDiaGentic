"""Agent Execution Gateway provider dispatch and retry (AG10).

The RequestRunner passed to GatewayQueueManager.enqueue. Resolves the request's
execution profile to a provider/model, dispatches through providers.services.execution
(the one allowed seam into providers — no provider-specific branches live here),
retries transient failures against the same profile, and falls back to
Validation/config failures (unknown profile, disabled provider, invalid
request, missing model, safety/config rejection) are terminal on first
occurrence — never retried.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.components.agents.gateway.session.dispatch import (
    _CancelledDuringDispatch,
    _dispatch_session_request,
    _is_session_request,
    _transition_owned_attempt,
)
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
# because AG10 explicitly calls out "unknown profile" (RES-EXP-001) as a
# no-fallback case; a future rate-limit-flavored RES code would currently be
# misclassified as terminal too — no adapter emits one today (rate limits
# surface as NET-*/TO-*/EXT-* in the existing adapters).

_TERMINAL_PREFIXES = ("VAL-", "RES-", "CON-", "CFG-", "VER-", "UNS-")
_TRANSIENT_PREFIXES = ("NET-", "TO-", "EXT-", "INT-", "IO-")


class _TerminalFailure(Exception):
    def __init__(self, original: AudiaGenticError) -> None:
        super().__init__(str(original))
        self.original = original


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


def resolve_retry_count(params: dict[str, Any]) -> int:
    """Resolve params.retry-count (or retry_count): additional attempts after
    the first failure, per profile. Default 1 (i.e. up to 2 total tries)."""
    value = first_present(params, "retry-count", "retry_count")
    if value is None:
        return 1
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AudiaGenticError(
            code="VAL-AGW-030",
            kind="agents",
            message="execution profile params.retry-count must be a non-negative integer",
            details={"value": value},
        )
    return value


def _raise_if_cancelled(project_root: Path, request_id: str) -> None:
    """Cooperative cancellation check: subprocess/HTTP calls can't be interrupted
    mid-flight, but the retry loop can stop advancing to the next attempt
    once a cancel has been recorded (RV23)."""
    if store.read_record(project_root, request_id)["cancel-requested"]:
        raise _CancelledDuringDispatch()


def _extract_model_id(result: dict[str, Any], bound_model_id: str | None) -> str | None:
    """Adapters are inconsistent about the result key (some return 'model',
    none currently return 'model-id', but normalize defensively) — fall back
    to the instance free-instance dispatch actually bound rather than
    silently losing it (AS105/AS101: there is no profile-level model_id
    anymore, only the resolved-model-id the queue bound at dispatch time)."""
    return result.get("model") or result.get("model-id") or bound_model_id


def _build_packet_ctx(
    project_root: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    model: dict[str, Any],
    *,
    dispatch_prompt: str,
) -> dict[str, Any]:
    """Build provider-neutral execution context from gateway-owned state.

    The gateway's project root is authoritative. Request metadata is correlation
    data only and cannot redirect provider execution into another directory.

    SH02: dispatch_prompt is the raw prompt body passed separately — it never
    lives in the persisted record (only prompt_digest does).
    """
    return {
        "request-id": record["request-id"],
        "execution-profile-id": profile["profile_id"],
        "provider-id": profile["provider_id"],
        "model-id": model.get("model-id") or model.get("resolved"),
        "model-alias": profile.get("model_alias"),
        "prompt-body": dispatch_prompt,
        "params": profile.get("params", {}),
        "working-root": str(project_root.resolve()),
        "stream-controls": dict(profile.get("params", {}).get("stream-controls") or {}),
        "source": record.get("source"),
        "metadata": record.get("metadata", {}),
    }


def _dispatch_one_attempt(
    project_root: Path,
    record: dict[str, Any],
    execution_profile_id: str,
    *,
    dispatch_prompt: str,
    manifest_id: str,
    context_fingerprint: str,
    component_profile: str,
    provider_isolation_tier: str,
    worker_timeout_seconds: float,
) -> dict[str, Any]:
    """Resolve profile/provider/model and call execute_provider once.

    Raises AudiaGenticError on any failure (validation or transient — caller
    classifies and decides retry). Returns the normalized provider
    result dict on success.

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    from audiagentic.components.agents.contracts.worker_protocol import WorkerExecutionIdentity
    from audiagentic.components.agents.gateway.queue.worker import (
        execute_isolated_provider_turn,
    )
    from audiagentic.components.agents.models.execution_profile_api import (
        resolve_execution_profile,
    )
    from audiagentic.components.providers import providers_api

    profile = resolve_execution_profile(project_root, execution_profile_id)
    provider_id = profile["provider_id"]
    if not providers_api.get_provider_runtime_config_state(project_root, provider_id)["enabled"]:
        raise AudiaGenticError(
            code="VAL-AGW-031",
            kind="agents",
            message="execution profile references a disabled provider",
            details={"provider-id": provider_id},
        )

    # AS105/AS101: free-instance dispatch binds a concrete model only at
    # dispatch time -- the queue writes the bound instance's model onto the
    # in-memory record it hands to the runner (never re-derived from the
    # profile, which now only names a compatible instance *set*).
    bound_model_id = record.get("resolved-model-id")

    packet_ctx = _build_packet_ctx(
        project_root,
        record,
        profile,
        {"model-id": bound_model_id},
        dispatch_prompt=dispatch_prompt,
    )
    provider_request = providers_api.ProviderExecutionRequest(
        project_root=project_root.resolve(),
        provider_id=provider_id,
        model_id=bound_model_id,
        model_alias=profile.get("model_alias"),
        packet_data=packet_ctx,
        worker_id=str(record.get("worker-id") or ""),
        attempt_epoch=int(record.get("attempt-epoch") or 0),  # noqa: RUF039
        provider_isolation_tier=provider_isolation_tier,  # type: ignore[arg-type]
    )
    identity = WorkerExecutionIdentity(
        worker_id=provider_request.worker_id,
        attempt_epoch=provider_request.attempt_epoch,
        manifest_id=manifest_id,
        context_fingerprint=context_fingerprint,
        project_root=str(project_root.resolve()),
        component_profile=component_profile,
        provider_isolation_tier=provider_isolation_tier,  # type: ignore[arg-type]
    )
    try:
        result = execute_isolated_provider_turn(
            identity=identity,
            execution_request=provider_request.to_mapping(),
            timeout_seconds=worker_timeout_seconds,
            activity_callback=lambda activity: _renew_activity(project_root, record, activity),
        )
    except TypeError as exc:
        # Preserve compatibility with test/delivery doubles written against
        # the pre-SH22 worker seam; real provider TypeErrors still propagate.
        if "activity_callback" not in str(exc):
            raise
        result = execute_isolated_provider_turn(
            identity=identity,
            execution_request=provider_request.to_mapping(),
            timeout_seconds=worker_timeout_seconds,
        )
    return dict(result.result_data)


def _renew_activity(project_root: Path, record: dict[str, Any], activity: Any) -> None:
    """Forward only authenticated worker activity to durable renewal."""
    from audiagentic.components.agents.contracts.worker_protocol import WorkerActivityEnvelope
    if not isinstance(activity, WorkerActivityEnvelope):
        return
    if activity.identity.worker_id != record.get("worker-id") or activity.identity.attempt_epoch != record.get("attempt-epoch"):
        return
    try:
        store.renew_owned_activity(
            project_root,
            record["request-id"],
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=activity.identity.worker_id,
            attempt_epoch=activity.identity.attempt_epoch,
            activity_seq=activity.activity_seq,
            activity_source=activity.activity_source,
            activity_lease_seconds=300.0,
        )
    except AudiaGenticError:
        # Activity is advisory evidence; a stale frame must not terminate a
        # provider turn or become a second lifecycle authority.
        logger.debug("ignored stale worker activity", exc_info=True)


def _try_profile_with_retries(
    project_root: Path,
    record: dict[str, Any],
    execution_profile_id: str,
    *,
    dispatch_prompt: str,
    manifest_id: str,
    context_fingerprint: str,
    component_profile: str,
    provider_isolation_tier: str,
    worker_timeout_seconds: float,
) -> dict[str, Any]:
    """Try one profile, retrying transient failures up to its retry-count.

    Raises _TerminalFailure immediately on a validation/config error (no
    retry). Raises the last AudiaGenticError if all attempts are transient
    failures.

    SH02: dispatch_prompt is passed through to each attempt for provider dispatch.
    """
    from audiagentic.components.agents.models.execution_profile_api import (
        resolve_execution_profile,
    )

    profile = resolve_execution_profile(project_root, execution_profile_id)
    retry_count = resolve_retry_count(profile.get("params", {}))
    max_attempts = retry_count + 1
    # AS105/AS101: bound at dispatch time (see _dispatch_one_attempt), never
    # re-derived from the profile, which now only names an instance set.
    bound_model_id = record.get("resolved-model-id")

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
                "execution-profile-id": execution_profile_id,
                "provider-id": profile.get("provider_id"),
                "model-id": bound_model_id,
                "attempt-index": attempt_num,
                "max-attempts": max_attempts,
                "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
            },
        )
        try:
            result = _dispatch_one_attempt(
                project_root,
                record,
                execution_profile_id,
                dispatch_prompt=dispatch_prompt,
                manifest_id=manifest_id,
                context_fingerprint=context_fingerprint,
                component_profile=component_profile,
                provider_isolation_tier=provider_isolation_tier,
                worker_timeout_seconds=worker_timeout_seconds,
            )
        except AudiaGenticError as exc:
            store.append_owned_attempt(
                project_root,
                record["request-id"],
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
                execution_profile_id=execution_profile_id,
                provider_id=profile.get("provider_id"),
                model_id=bound_model_id,
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
            model_id = _extract_model_id(result, bound_model_id)
            store.append_owned_attempt(
                project_root,
                record["request-id"],
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
                execution_profile_id=execution_profile_id,
                provider_id=profile.get("provider_id"),
                model_id=model_id,
                state="completed",
                started_at=started_at,
                finished_at=now_iso_z(),
            )
            output_text = result.get("output")
            return {
                "provider-id": result.get("provider-id", profile.get("provider_id")),
                "model-id": model_id,
                "output": output_text,
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
            details={"execution-profile-id": execution_profile_id},
        )
    raise last_exc


def dispatch_request(
    project_root: Path,
    record: dict[str, Any],
    *,
    dispatch_prompt: str,
    preallocated_session_id: str | None = None,
    manifest_id: str,
    context_fingerprint: str,
    component_profile: str,
    provider_isolation_tier: str,
    worker_timeout_seconds: float,
) -> dict[str, Any]:
    """Dispatch a queued/running gateway request record to completion.

    RequestRunner signature — passed to GatewayQueueManager.enqueue. The
    record is already 'running' when this is called (the queue manager
    transitions it before invoking the runner). Persists the terminal
    ('completed' or 'failed') state before returning.

    Sessionful requests (session-id / session-keep-alive) route to the live
    SessionRuntime via _dispatch_session_request — no retry.

    SH23: a no-isolation provider (e.g. gpt-auto — CDP-attached to one
    already-running browser) has no safe disposable-subprocess-per-attempt
    story, so it can never satisfy worker_host.py's full-isolation gate.
    Rather than leaving it permanently unreachable on a plain one-shot
    submit, route it through the same ephemeral-session pattern used above:
    session_id stays None, session-keep-alive stays false, so
    _dispatch_session_request opens a session, runs exactly one turn, and
    its existing post-turn logic auto-closes it — no new session-runtime
    code, no retry-count (matches the session path's existing "no retry on
    a stateful conversation" behavior). full-isolation and partial-isolation
    dispatch is completely unaffected — they still take the subprocess path
    below and partial-isolation still fails closed there (UNS-AGW-076).

    Cancellation is cooperative and checked only BETWEEN attempts
    (_raise_if_cancelled) — an in-flight execute_provider call
    (a subprocess or HTTP request already underway) is never interrupted
    mid-flight. A cancel recorded while an attempt is running takes effect
    only once that attempt returns (RV34 finding).

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    if _is_session_request(record) or provider_isolation_tier == "no-isolation":
        return _dispatch_session_request(
            project_root,
            record,
            dispatch_prompt=dispatch_prompt,
            preallocated_session_id=preallocated_session_id,
            context_fingerprint=context_fingerprint,
        )

    try:
        _raise_if_cancelled(project_root, record["request-id"])
        outcome = _try_profile_with_retries(
            project_root,
            record,
            record["execution-profile-id"],
            dispatch_prompt=dispatch_prompt,
            manifest_id=manifest_id,
            context_fingerprint=context_fingerprint,
            component_profile=component_profile,
            provider_isolation_tier=provider_isolation_tier,
            worker_timeout_seconds=worker_timeout_seconds,
        )
    except _CancelledDuringDispatch:
        return _transition_owned_attempt(project_root, record, "cancelled")
    except _TerminalFailure as exc:
        error = exc.original
    except AudiaGenticError as exc:
        error = exc
    else:
        return _transition_owned_attempt(
            project_root,
            record,
            "completed",
            updates={**outcome, "finished-at": now_iso_z()},
        )
    return _transition_owned_attempt(
        project_root,
        record,
        "failed",
        updates={"error": error, "finished-at": now_iso_z()},
    )
