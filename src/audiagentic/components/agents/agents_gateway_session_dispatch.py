"""Session dispatch extracted from agents_gateway_dispatch.py (SH18).

Owns the sessionful dispatch path: _is_session_request, _session_output_from_result,
_post_turn_close_continued_session_if_quiescent, _dispatch_session_request,
_transition_owned_attempt. Moved here to reduce the line count of dispatch.py
while keeping cohesion within each module.

Dispatch edges one-way: agents_gateway_dispatch -> this module (no back-imports).
Shared helpers from dispatch.py are imported lazily inside functions to avoid
module-level cycles.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

# ── AS28 slice 4a helpers ────────────────────────────────────────
def _build_default_surface_hint(provider_id: str) -> Any:
    """Build a default SurfaceHint for ACP-based provider surfaces.

    Uses ``<provider-id>-acp`` as the surface id, matching the naming
    convention in provider descriptors (e.g. opencode-acp).
    """
    from audiagentic.components.providers.contracts.session_surface import (
        SurfaceHint,
    )

    return SurfaceHint(surface_id=f"{provider_id}-acp")


def _is_session_request(record: dict[str, Any]) -> bool:
    return bool(record.get("session-id") or record.get("session-keep-alive"))


def _session_output_from_result(result: Any) -> str | None:
    """Read the bounded final summary from a SessionTurnResult.

    Output is produced inside the ACP adapter; agents never reconstructs
    output from protocol events. The adapter carries assistant-text
    fragments only (no thought, tool args, provider refs)."""
    return result.final_summary if hasattr(result, "final_summary") else None


def _post_turn_close_continued_session_if_quiescent(
    project_root: Path,
    session_id: str,
    runtime: Any,
) -> None:
    """Close a continued session after its turn if keep_alive=false and quiescent.

    Best-effort: if the session is not quiescent (other turns pending), or if
    the close fails for any reason, the error is logged but does not affect
    the request outcome.
    """
    try:
        is_quiescent = runtime.session_is_quiescent(session_id)
    except Exception:
        logger.debug(
            "post-turn session quiescence check failed; attempting explicit close",
            extra={"session-id": session_id},
            exc_info=True,
        )
        is_quiescent = True
    if not is_quiescent:
        logger.debug(
            "post-turn session close deferred because session is not quiescent",
            extra={"session-id": session_id},
        )
        return
    runtime.close_session(project_root, session_id, reason="post-turn-close")


def _dispatch_session_request(
    project_root: Path,
    record: dict[str, Any],
    *,
    dispatch_prompt: str,
    context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Dispatch a sessionful request through the live SessionRuntime (AS04).

    No retry on this path — retrying inside a stateful conversation is not
    idempotent. Any turn failure is terminal for the request.

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_api import resolve_profile
    from audiagentic.components.agents.agents_gateway_sessions import get_session_runtime
    from audiagentic.components.agents.agents_paths import gateway_request_dir

    request_id = record["request-id"]
    agent_profile_id = record["agent-profile-id"]
    runtime = get_session_runtime()

    profile = resolve_profile(project_root, agent_profile_id)
    provider_id = profile["provider_id"]

    session_id = record.get("session-id")
    started_at = now_iso_z()
    request_runtime = None
    request_runtime_root = gateway_request_dir(project_root, request_id) / "runtime"
    try:
        if session_id is None:
            # keep-alive: open a new session bound to this profile
            from audiagentic.runtime.harness.config import load_harness_config
            from audiagentic.runtime.harness.pi.request_runtime import create_request_runtime

            request_runtime = create_request_runtime(
                request_runtime_root,
                project_root,
                request_id,
                load_harness_config(project_root=project_root),
                runtime_root=request_runtime_root / "pi",
            )
            # AS28 slice 4a: pass provider context — the session runtime
            # resolves the transport via providers_api.prepare_provider_session_transport.
            # AS08: persist execution-context fingerprint on session create.
            profile_model_id = profile.get("model_id")
            params = profile.get("params", {})
            session_record = runtime.open_session(
                project_root,
                agent_profile_id=agent_profile_id,
                provider_id=provider_id,
                model_id=profile_model_id,
                surface_hint=_build_default_surface_hint(provider_id),
                correlation_id=record.get("correlation-id"),
                context_fingerprint=context_fingerprint,
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
            record = store.update_owned_running_session(
                project_root,
                request_id,
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
                session_id=session_id,
            )
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
            # AS08: validate execution-context fingerprint exact match on continuation.
            if context_fingerprint is not None:
                stored_fingerprint = _get_stored_context_fingerprint(session_record)
                if stored_fingerprint and context_fingerprint != stored_fingerprint:
                    raise AudiaGenticError(
                        code="CON-AGW-101",
                        kind="agents",
                        message="execution context fingerprint does not match the session's context",
                        details={
                            "session-id": session_id,
                            "stored-fingerprint": stored_fingerprint,
                            "request-fingerprint": context_fingerprint,
                        },
                    )
            # Update lifetime bounds when continuing with keep-alive and new
            # policy values. Bounds apply to the in-memory handle so the
            # updated policy is effective for this and future turns.
            if record.get("session-keep-alive") is True and (
                record.get("session-idle-timeout-seconds") is not None
                or record.get("session-max-lifetime-seconds") is not None
            ):
                try:
                    runtime.update_session_bounds(
                        session_id,
                        idle_timeout_seconds=record.get("session-idle-timeout-seconds"),
                        max_lifetime_seconds=record.get("session-max-lifetime-seconds"),
                    )
                except AudiaGenticError as exc:
                    raise AudiaGenticError(
                        code="VAL-AGW-098",
                        kind="agents",
                        message=(
                            "session lifetime bounds provided with session_id and "
                            "session_keep_alive, but the runtime cannot update policy "
                            "on an existing session"
                        ),
                        details={
                            "session-id": session_id,
                            "underlying-code": exc.code,
                            "underlying-message": exc.message,
                        },
                    ) from exc

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
        if request_runtime is not None:
            from audiagentic.runtime.harness.pi.request_runtime import cleanup_request_runtime
            cleanup_request_runtime(request_runtime)
        return _transition_owned_attempt(project_root, record, "cancelled")
    except AudiaGenticError as exc:
        if request_runtime is not None:
            from audiagentic.runtime.harness.pi.request_runtime import quarantine_request_runtime
            quarantine_request_runtime(request_runtime, request_runtime_root.parent / "quarantine")
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
        # request, not a completed one. Preserve bounded result diagnostics so
        # operators can still see that the turn produced terminal evidence.
        session_record = session_store.read_session_record(project_root, session_id)
        model_id = session_record.get("model-id") or profile.get("model_id")
        output_text = _session_output_from_result(result)
        store.append_owned_attempt(
            project_root, request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            agent_profile_id=agent_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            state="cancelled",
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        # Post-turn: close continued session if keep_alive=false and quiescent.
        if (
            record.get("session-id") is not None
            and record.get("session-keep-alive") is False
        ):
            _post_turn_close_continued_session_if_quiescent(
                project_root, session_id, runtime,
            )
        if request_runtime is not None and record.get("session-keep-alive") is not True:
            from audiagentic.runtime.harness.pi.request_runtime import cleanup_request_runtime
            cleanup_request_runtime(request_runtime)
        return _transition_owned_attempt(
            project_root, record, "cancelled",
            updates={
                "provider-id": provider_id,
                "model-id": model_id,
                "output": output_text,
                "completion": {
                    "stop-reason": result.stop_reason,
                    "binding": binding_store.public_binding_projection(session_record.get("binding")),
                    "total-events": result.observations_delivered + result.dropped_observations,
                    "dropped-events": result.dropped_observations,
                },
                "usage": None,
                "session-id": session_id,
                "finished-at": now_iso_z(),
            },
        )

    session_record = session_store.read_session_record(project_root, session_id)
    model_id = session_record.get("model-id") or profile.get("model_id")
    output_text = _session_output_from_result(result)
    from audiagentic.components.agents.agents_gateway_dispatch import _write_output_chunk
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
    # Post-turn: close continued session if keep_alive=false and quiescent.
    if (
        record.get("session-id") is not None
        and record.get("session-keep-alive") is False
    ):
        _post_turn_close_continued_session_if_quiescent(
            project_root, session_id, runtime,
        )
    if request_runtime is not None and record.get("session-keep-alive") is not True:
        from audiagentic.runtime.harness.pi.request_runtime import cleanup_request_runtime
        cleanup_request_runtime(request_runtime)
    return _transition_owned_attempt(
        project_root, record, "completed",
        updates={
            "provider-id": provider_id,
            "model-id": model_id,
            "output": output_text,
            "completion": {
                "stop-reason": result.stop_reason,
                "binding": binding_store.public_binding_projection(session_record.get("binding")),
                "total-events": result.observations_delivered + result.dropped_observations,
                "dropped-events": result.dropped_observations,
            },
            "usage": None,
            "session-id": session_id,
            "finished-at": now_iso_z(),
        },
    )


class _CancelledDuringDispatch(Exception):
    """Raised when a persisted cancel-requested flag is observed between attempts."""


def _params_get(params: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in params:
            return params[key]
    return None


def _raise_if_cancelled(project_root: Path, request_id: str) -> None:
    """Cooperative cancellation check: subprocess/HTTP calls can't be interrupted
    mid-flight, but the retry loop can stop advancing to the next attempt
    once a cancel has been recorded (RV23)."""
    if store.read_record(project_root, request_id)["cancel-requested"]:
        raise _CancelledDuringDispatch()


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
