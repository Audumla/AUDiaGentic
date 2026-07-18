"""Agent LLM Gateway provider dispatch and retry (AG10).

The RequestRunner passed to GatewayQueueManager.enqueue. Resolves the request's
agent profile to a provider/model, dispatches through providers.services.execution
(the one allowed seam into providers — no provider-specific branches live here),
retries transient failures against the same profile, and falls back to
Validation/config failures (unknown profile, disabled provider, invalid
request, missing model, safety/config rejection) are terminal on first
occurrence — never retried.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

_ENV_STREAM_OUTPUT = "AUDIAGENTIC_GATEWAY_STREAM_OUTPUT"


def _write_output_chunk(project_root: Path, request_id: str, text: str | None, attempt_index: int) -> None:
    """Append an output chunk to <request-dir>/output.ndjson if streaming is enabled.

    Fire-and-forget — never raises. Controlled by AUDIAGENTIC_GATEWAY_STREAM_OUTPUT env var.
    Set to any truthy value (e.g. '1') to enable; unset or empty to disable."""
    if not os.environ.get(_ENV_STREAM_OUTPUT):
        return
    if not text:
        return
    try:
        from audiagentic.components.agents.agents_paths import gateway_root

        out_path = gateway_root(project_root) / request_id / "output.ndjson"
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"attempt": attempt_index, "text": text}) + "\n")
    except Exception:  # noqa: BLE001
        logger.debug(
            "failed to write output chunk (non-fatal)",
            extra={"request-id": request_id},
            exc_info=True,
        )


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


def _raise_if_cancelled(project_root: Path, request_id: str) -> None:
    """Cooperative cancellation check: subprocess/HTTP calls can't be interrupted
    mid-flight, but the retry loop can stop advancing to the next attempt
    once a cancel has been recorded (RV23)."""
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
        "agent-profile-id": profile["profile_id"],
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
    agent_profile_id: str,
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
    from audiagentic.components.agents.agents_api import resolve_profile
    from audiagentic.components.agents.agents_gateway_worker import (
        execute_isolated_provider_turn,
    )
    from audiagentic.components.agents.contracts.worker_protocol import (
        WorkerExecutionIdentity,
    )
    from audiagentic.components.providers import providers_api

    profile = resolve_profile(project_root, agent_profile_id)
    provider_id = profile["provider_id"]
    if not providers_api.get_provider_runtime_config_state(
        project_root, provider_id
    )["enabled"]:
        raise AudiaGenticError(
            code="VAL-AGW-031",
            kind="agents",
            message="agent profile references a disabled provider",
            details={"provider-id": provider_id},
        )

    packet_ctx = _build_packet_ctx(
        project_root,
        record,
        profile,
        {"model-id": profile.get("model_id")},
        dispatch_prompt=dispatch_prompt,
    )
    provider_request = providers_api.ProviderExecutionRequest(
        project_root=project_root.resolve(),
        provider_id=provider_id,
        model_id=profile.get("model_id"),
        model_alias=profile.get("model_alias"),
        packet_data=packet_ctx,
        worker_id=str(record.get("worker-id") or ""),
        attempt_epoch=int(record.get("attempt-epoch") or 0),
        provider_isolation_tier=provider_isolation_tier,
    )
    identity = WorkerExecutionIdentity(
        worker_id=provider_request.worker_id,
        attempt_epoch=provider_request.attempt_epoch,
        manifest_id=manifest_id,
        context_fingerprint=context_fingerprint,
        project_root=str(project_root.resolve()),
        component_profile=component_profile,
        provider_isolation_tier=provider_isolation_tier,
    )
    result = execute_isolated_provider_turn(
        identity=identity,
        execution_request=provider_request.to_mapping(),
        timeout_seconds=worker_timeout_seconds,
    )
    return dict(result.result_data)


def _try_profile_with_retries(
    project_root: Path,
    record: dict[str, Any],
    agent_profile_id: str,
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
            result = _dispatch_one_attempt(
                project_root,
                record,
                agent_profile_id,
                dispatch_prompt=dispatch_prompt,
                manifest_id=manifest_id,
                context_fingerprint=context_fingerprint,
                component_profile=component_profile,
                provider_isolation_tier=provider_isolation_tier,
                worker_timeout_seconds=worker_timeout_seconds,
            )
        except AudiaGenticError as exc:
            store.append_owned_attempt(
                project_root, record["request-id"],
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
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
            store.append_owned_attempt(
                project_root, record["request-id"],
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
                agent_profile_id=agent_profile_id,
                provider_id=profile.get("provider_id"),
                model_id=model_id,
                state="completed",
                started_at=started_at,
                finished_at=now_iso_z(),
            )
            output_text = result.get("output")
            _write_output_chunk(project_root, record["request-id"], output_text, attempt_num)
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
            details={"agent-profile-id": agent_profile_id},
        )
    raise last_exc


def _is_session_request(record: dict[str, Any]) -> bool:
    return bool(record.get("session-id") or record.get("session-keep-alive"))


def _session_output_from_result(result: Any) -> str | None:
    """Concatenate assistant-message texts from an AcpResult into the
    gateway record's output field (same contract keys as one-shot dispatch).

    ACP agents stream agent_message_chunk fragments — mid-word splits are
    normal — so chunks are joined with NO separator (AS07 live-gate finding:
    a newline join corrupted output into 'TOKEN\\n STORE\\nD\\n.')."""
    texts = [
        event.text
        for event in result.events
        if event.kind == "assistant-message" and event.text
    ]
    # Text carried by events the transport's rolling budgets EVICTED — with
    # FIFO eviction those are always the OLDEST chunks, so they lead.
    overflow = getattr(result, "overflow_text", None)
    if overflow:
        texts.insert(0, overflow)
    return "".join(texts) if texts else None


def _dispatch_session_request(
    project_root: Path,
    record: dict[str, Any],
    *,
    dispatch_prompt: str,
) -> dict[str, Any]:
    """Dispatch a sessionful request through the live SessionRuntime (AS04).

    No retry on this path — retrying inside a stateful conversation is not
    idempotent. Any turn failure is terminal for the request.

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_api import resolve_profile
    from audiagentic.components.agents.agents_gateway_sessions import get_session_runtime
    from audiagentic.components.providers import providers_api

    request_id = record["request-id"]
    agent_profile_id = record["agent-profile-id"]
    runtime = get_session_runtime()

    profile = resolve_profile(project_root, agent_profile_id)
    provider_id = profile["provider_id"]

    session_id = record.get("session-id")
    started_at = now_iso_z()
    try:
        if session_id is None:
            # keep-alive: open a new session bound to this profile
            prepared_launch = providers_api.prepare_provider_acp_launch(
                project_root,
                provider_id=provider_id,
                model_id=profile.get("model_id"),
                model_alias=profile.get("model_alias"),
            )
            model_id = prepared_launch.model_id
            params = profile.get("params", {})
            session_record = runtime.open_session(
                project_root,
                agent_profile_id=agent_profile_id,
                launch=prepared_launch.launch,
                provider_id=provider_id,
                model_id=model_id,
                correlation_id=record.get("correlation-id"),
                # Request value wins over profile params; 0 disables the bound
                # (RV513) — use explicit None checks so 0 survives resolution.
                idle_timeout_seconds=(
                    record.get("session-idle-timeout-seconds")
                    if record.get("session-idle-timeout-seconds") is not None
                    else _params_get(params, "session-idle-timeout-seconds", "session_idle_timeout_seconds")
                ),
                max_lifetime_seconds=(
                    record.get("session-max-lifetime-seconds")
                    if record.get("session-max-lifetime-seconds") is not None
                    else _params_get(params, "session-max-lifetime-seconds", "session_max_lifetime_seconds")
                ),
                # RV680: per-turn deadline and opt-in event-silence watchdog,
                # profile-param driven; None → runtime defaults, 0 disables.
                turn_timeout_seconds=_params_get(
                    params, "session-turn-timeout-seconds", "session_turn_timeout_seconds"
                ),
                turn_silence_timeout_seconds=_params_get(
                    params,
                    "session-turn-silence-timeout-seconds",
                    "session_turn_silence_timeout_seconds",
                ),
            )
            session_id = session_record["session-id"]
        else:
            # continue: the session must exist and be bound to the same profile
            session_record = session_store.read_session_record(project_root, session_id)
            if session_record["agent-profile-id"] != agent_profile_id:
                raise AudiaGenticError(
                    code="VAL-AGW-060",
                    kind="agents",
                    message="request agent profile does not match the session's profile",
                    details={
                        "session-id": session_id,
                        "session-profile": session_record["agent-profile-id"],
                        "request-profile": agent_profile_id,
                    },
                )

        _raise_if_cancelled(project_root, request_id)
        store.record_gateway_timeline(
            project_root, request_id, "attempt.started",
            state=store.read_record(project_root, request_id)["state"],
            attributes={
                "agent-profile-id": agent_profile_id,
                "provider-id": provider_id,
                "session-id": session_id,
                "attempt-index": 0,
                "max-attempts": 1,
            },
        )
        result = runtime.prompt_in_session(
            project_root, session_id, dispatch_prompt,
            request_id=request_id,
            correlation_id=record.get("correlation-id"),
        )
    except _CancelledDuringDispatch:
        return _transition_owned_attempt(project_root, record, "cancelled")
    except AudiaGenticError as exc:
        store.append_owned_attempt(
            project_root, request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            agent_profile_id=agent_profile_id,
            provider_id=provider_id,
            model_id=profile.get("model_id"),
            state="failed",
            error=exc,
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        return _transition_owned_attempt(
            project_root, record, "failed",
            updates={"error": exc, "session-id": session_id, "finished-at": now_iso_z()},
        )

    if result.stop_reason == "cancelled":
        # RV680: a turn interrupted by protocol-level cancel is a cancelled
        # request, not a completed one — the session itself stays usable.
        return _transition_owned_attempt(
            project_root, record, "cancelled",
            updates={"session-id": session_id, "finished-at": now_iso_z()},
        )

    session_record = session_store.read_session_record(project_root, session_id)
    model_id = session_record.get("model-id") or profile.get("model_id")
    output_text = _session_output_from_result(result)
    _write_output_chunk(project_root, request_id, output_text, 0)
    store.append_owned_attempt(
        project_root, request_id,
        owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
        agent_profile_id=agent_profile_id,
        provider_id=provider_id,
        model_id=model_id,
        state="completed",
        started_at=started_at,
        finished_at=now_iso_z(),
    )
    return _transition_owned_attempt(
        project_root, record, "completed",
        updates={
            "provider-id": provider_id,
            "model-id": model_id,
            "output": _session_output_from_result(result),
            "completion": {
                "stop-reason": result.stop_reason,
                "provider-session-ref": session_record.get("provider-session-ref"),
                "total-events": result.total_events,
                "dropped-events": result.dropped_events,
            },
            "usage": None,
            "session-id": session_id,
            "finished-at": now_iso_z(),
        },
    )


def dispatch_request(
    project_root: Path,
    record: dict[str, Any],
    *,
    dispatch_prompt: str,
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

    Cancellation is cooperative and checked only BETWEEN attempts
    (_raise_if_cancelled) — an in-flight execute_provider call
    (a subprocess or HTTP request already underway) is never interrupted
    mid-flight. A cancel recorded while an attempt is running takes effect
    only once that attempt returns (RV34 finding).

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    if _is_session_request(record):
        return _dispatch_session_request(project_root, record, dispatch_prompt=dispatch_prompt)

    try:
        _raise_if_cancelled(project_root, record["request-id"])
        outcome = _try_profile_with_retries(
            project_root,
            record,
            record["agent-profile-id"],
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
            project_root, record, "completed",
            updates={**outcome, "finished-at": now_iso_z()},
        )
    return _transition_owned_attempt(
        project_root, record, "failed",
        updates={"error": error, "finished-at": now_iso_z()},
    )


def _transition_owned_attempt(
    project_root: Path,
    record: dict[str, Any],
    new_state: str,
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a terminal state only while this worker attempt still owns it."""
    return store.transition_owned_terminal(
        project_root,
        record["request-id"],
        new_state,
        updates=updates,
        owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
    )
