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

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

_TURN_CALL_GRACE_SECONDS = 15.0


def _terminal_session_diagnostics(session_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """Return sparse facts needed to repair a continuation rejection.

    RES-AGW-003 is deliberately stable for callers, but ``state`` alone is
    not enough to explain why a session stopped accepting turns.  Keep the
    durable lifecycle reason, timestamps, and whether a provider conversation
    remains bound in the error so operators can choose explicit resume versus
    a new session without guessing or resubmitting blindly.
    """
    details: dict[str, Any] = {
        "session-id": session_id,
        "state": record.get("state"),
        "close-reason": record.get("close-reason"),
        "suggestion": (
            "call session_resume to continue the same provider conversation"
            if record.get("state") in {"failed", "closed", "expired"}
            else "inspect the gateway runtime before retrying"
        ),
    }
    timing = record.get("timing")
    if isinstance(timing, dict):
        for key in ("created-at", "last-activity-at", "updated-at", "closed-at"):
            value = timing.get(key)
            if value:
                details[key] = value
    provider = record.get("provider")
    metadata = provider.get("metadata") if isinstance(provider, dict) else None
    if isinstance(metadata, dict):
        for key in ("provider-session-id", "chat-url", "unresolved-turn-pending"):
            value = metadata.get(key)
            if value not in (None, "", False):
                details[f"provider-{key}"] = value
    return details


# ── AS28 slice 4a helpers ────────────────────────────────────────
# GP13 (scoped, 2026-08-17): a resume-eligibility refusal from AS49's
# validate_resume_eligibility() (see resume.py's module docstring for the
# full taxonomy) is EXPECTED input to the auto-resume decision -- it just
# means this particular closed session can't be transparently upgraded, so
# the caller falls back to today's RES-AGW-003 behavior. CON-AGW-116
# (idempotent replay of a previously-failed control id) is included: a
# prior auto-resume attempt for this exact source already failed, so
# retrying it again would only reproduce the same refusal. Anything NOT in
# this set (a store failure, a lost ownership fence, a genuine internal
# defect) must never be silently swallowed into an innocuous "session
# isn't active" -- it has to surface as itself.
_AUTO_RESUME_EXPECTED_REFUSAL_CODES = frozenset(
    {
        "CON-AGW-110",  # source session is not terminal
        "RES-AGW-111",  # source session has no usable provider binding
        "UNS-AGW-112",  # resolved surface does not support resume-by-ref
        "VER-AGW-113",  # surface id or ref namespace incompatible
        "CON-AGW-115",  # execution context fingerprint unknown or mismatched
        "CON-AGW-116",  # idempotent replay of a control id that already failed
        "UNS-AGW-117",  # surface declares resume-by-ref but evidence unvalidated
    }
)


def _auto_resume_shutdown_closed_session(
    project_root: Path,
    runtime: Any,
    *,
    source_session_id: str,
    record: dict[str, Any],
    context_fingerprint: str | None,
    request_runtime_root: Path,
    project_name: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Transparently reattach a session closed by a gateway shutdown.

    Reproduced live 2026-08-17: a force gateway restart (loading unrelated
    fixes) explicitly closed every live session machine-wide
    (close-reason=shutdown) as part of its own stop sequence. A concurrent
    caller's next continuation against one of those sessions got a hard
    RES-AGW-003 even though the closed record still carried everything
    needed to resume the same live provider conversation. Deliberately
    narrow in scope (see the caller's own state==closed and
    close-reason==shutdown guard): this function is never reached for a
    genuinely failed session (that must still require the caller's own
    explicit session_resume, never be silently papered over) or any other
    close reason (a policy/lifecycle boundary this tactical patch does not
    attempt to reinterpret -- see plan item GP13's own notes for the full
    unified-activation design this is deliberately NOT building).

    Reuses AS49's existing resume_session() machinery as-is -- no new
    concurrency primitive. A control id deterministic in the source
    session id means concurrent racing continuations against the same
    closed session converge on resume.py's existing idempotency-by-
    control-id lookup and resolve to the SAME successor, rather than each
    minting its own. This is a real, accepted, narrower guarantee than
    GP13's full per-source reservation model: an EXPLICIT caller resume
    (a different control id) racing this SAME source session could still
    mint a second, different successor. Not closed by this patch.

    Returns (new_session_id, new_session_record, updated_request_record).
    Raises the original RES-AGW-003 for any expected resume-ineligibility
    refusal (see _AUTO_RESUME_EXPECTED_REFUSAL_CODES); any other error
    (a lost ownership fence, a store failure, an internal resume defect)
    propagates as itself -- it must never be masked as mere ineligibility.
    """
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    try:
        new_session_record = runtime.resume_session(
            project_root,
            source_session_id,
            # Deterministic, not request-scoped: two concurrent
            # continuations against the SAME closed source must resolve to
            # the same idempotency lookup, which a request-id-derived key
            # would not give them.
            control_id=f"auto-resume:{source_session_id}",
            execution_context_fingerprint=context_fingerprint or record.get("context-fingerprint"),
            request_runtime_root=request_runtime_root,
            project_name=project_name,
        )
    except AudiaGenticError as exc:
        if exc.code in _AUTO_RESUME_EXPECTED_REFUSAL_CODES:
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="session is not active and cannot be continued",
                details={
                    **_terminal_session_diagnostics(
                        source_session_id,
                        session_store.read_session_record(project_root, source_session_id),
                    ),
                    "auto-resume-attempted": True,
                    "auto-resume-refusal-code": exc.code,
                },
            ) from exc
        raise

    new_session_id = str(new_session_record["session-id"])
    logger.info(
        "gpt-auto session transparently resumed after shutdown closure",
        extra={
            "source-session-id": source_session_id,
            "resumed-session-id": new_session_id,
        },
    )
    # GP13 code-review consultation: retarget the durable request to the
    # successor BEFORE any provider submission proceeds. update_owned_
    # running_session() is already fenced on owner_epoch/worker_id/
    # attempt_epoch (see store/_transitions.py) -- a lost fence here means
    # this worker no longer has authority over the request and must raise,
    # never silently fall back to the old RES-AGW-003 as if resume merely
    # wasn't eligible.
    updated_record = store.update_owned_running_session(
        project_root,
        record["request-id"],
        owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
        session_id=new_session_id,
        provider_metadata=session_store.session_provider_metadata(new_session_record),
    )
    return new_session_id, new_session_record, updated_record


def _build_surface_hint(profile: dict[str, Any]) -> Any:
    """Build the surface hint from the resolved execution profile.

    Surface identity is configuration-owned and must be explicit. Provider
    naming conventions and generic ACP defaults are not valid resolution.
    """
    from audiagentic.components.providers.providers_api import SurfaceHint

    surface_id = profile.get("surface_id")
    if not isinstance(surface_id, str) or not surface_id.strip():
        raise AudiaGenticError(
            code="RES-AGW-103",
            kind="agents",
            message="execution profile must declare a session surface",
            details={
                "execution-profile-id": profile.get("profile_id"),
                "provider-id": profile.get("provider_id"),
            },
        )
    return SurfaceHint(surface_id=surface_id)


def _is_session_request(record: dict[str, Any]) -> bool:
    return bool(record.get("session-id") or record.get("session-keep-alive"))


def _admitted_project_name(record: dict[str, Any]) -> str | None:
    """Return the frozen project name from an admitted request context."""
    template_context = record.get("template-context")
    project = template_context.get("project") if isinstance(template_context, dict) else None
    name = project.get("name") if isinstance(project, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


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
    preallocated_session_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a sessionful request through the live SessionRuntime (AS04).

    No retry on this path — retrying inside a stateful conversation is not
    idempotent. Any turn failure is terminal for the request.

    SH02: dispatch_prompt is the raw prompt body, passed separately from the
    persisted record (which only carries prompt_digest).
    """
    from audiagentic.components.agents.agents_paths import gateway_request_dir
    from audiagentic.components.agents.gateway import profiles as profiles_mod
    from audiagentic.components.agents.gateway.session import bindings as binding_store
    from audiagentic.components.agents.gateway.session import sessions_store as session_store
    from audiagentic.components.agents.gateway.session.sessions import (
        DEFAULT_TURN_TIMEOUT_SECONDS,
        get_session_runtime,
    )
    from audiagentic.components.providers import providers_api

    request_id = record["request-id"]
    execution_profile_id = record["execution-profile-id"]
    runtime = get_session_runtime()
    project_name = _admitted_project_name(record)

    admitted_snapshot = profiles_mod.snapshot_from_record(record)
    if admitted_snapshot is not None:
        profile = profiles_mod.profile_mapping_from_snapshot(admitted_snapshot, record)
    elif profiles_mod.get_gateway_registry() is not None:
        raise AudiaGenticError(
            code="CON-AGW-101", kind="agents",
            message="shared gateway session has no immutable admission profile snapshot",
            details={"request-id": record.get("request-id")},
        )
    else:
        from audiagentic.components.agents.models.execution_profile_api import (
            resolve_execution_profile,
        )

        profile = resolve_execution_profile(project_root, execution_profile_id)
    provider_id = profile["provider_id"]
    params = profile.get("params", {})
    # AS88 composition facts are admission-owned.  Dispatch forwards only
    # identifiers/digests already present on the admitted request; it never
    # re-resolves or copies Agent/Role/Profile definitions into a session.
    composition = record.get("composition")
    if not isinstance(composition, dict):
        composition = {}
    context_id = record.get("context-id") or composition.get("context-id")
    agent_definition_id = record.get("agent-definition-id") or composition.get("agent-definition-id")
    agent_definition_digest = record.get("agent-definition-digest") or composition.get("agent-definition-digest")
    role_ids = record.get("role-ids") or composition.get("role-ids")
    role_set_digest = record.get("role-set-digest") or composition.get("role-set-digest")
    execution_profile_digest = record.get("execution-profile-digest") or composition.get("execution-profile-digest")
    effective_capability_digest = record.get("effective-capability-digest") or composition.get("effective-capability-digest")

    session_id = record.get("session-id")
    started_at = now_iso_z()
    request_runtime = None
    request_runtime_root = gateway_request_dir(project_root, request_id) / "runtime"
    try:
        is_new_session = session_id is None or (
            preallocated_session_id is not None and session_id == preallocated_session_id
        )
        if is_new_session:
            # keep-alive: open a new session bound to this profile
            request_runtime_root.mkdir(parents=True, exist_ok=True)
            request_runtime = request_runtime_root
            from audiagentic.components.providers import providers_api

            mcp_entries = providers_api.collect_management_mcp_launch_entries(project_root)
            # AS28 slice 4a: pass provider context — the session runtime
            # resolves the transport via providers_api.prepare_provider_session_transport.
            # AS08: persist execution-context fingerprint on session create.
            # AS105/AS101: free-instance dispatch binds a concrete model only
            # at dispatch time; the queue writes it onto the in-memory record
            # before calling the runner (never re-derived from the profile,
            # which now only names a compatible instance set).
            profile_model_id = record.get("resolved-model-id")
            # AS08/AS49: stamp the session's binding with this request's own
            # SH02 manifest fingerprint (already computed once, correctly, at
            # admission -- see execution_context.py's build_manifest). Reused
            # for both fields: identity vs execution drift aren't split out
            # anywhere else in the manifest today, so a single fingerprint
            # that must match exactly on both continuation (AS08) and resume
            # (AS49) is the correct, non-speculative behavior until a real
            # need for a finer split shows up.
            manifest_context_fingerprint = context_fingerprint or record.get("context-fingerprint")
            session_record = runtime.open_session(
                project_root,
                execution_profile_id=execution_profile_id,
                provider_id=provider_id,
                model_id=profile_model_id,
                session_id=session_id,
                surface_hint=_build_surface_hint(profile),
                correlation_id=record.get("correlation-id"),
                request_runtime_root=request_runtime_root,
                mcp_entries=mcp_entries,
                identity_context_fingerprint=manifest_context_fingerprint,
                execution_context_fingerprint=manifest_context_fingerprint,
                context_id=context_id,
                agent_definition_id=agent_definition_id,
                agent_definition_digest=agent_definition_digest,
                role_ids=role_ids,
                role_set_digest=role_set_digest,
                execution_profile_digest=execution_profile_digest,
                effective_capability_digest=effective_capability_digest,
                capacity_source_id=record.get("resolved-source-id"),
                project_name=project_name,
                # Request value wins over profile params; 0 disables the bound
                # (RV513) — use explicit None checks so 0 survives resolution.
                idle_timeout_seconds=(
                    record.get("session-idle-timeout-seconds")
                    if record.get("session-idle-timeout-seconds") is not None
                    else first_present(
                        params, "session-idle-timeout-seconds", "session_idle_timeout_seconds"
                    )
                ),
                max_lifetime_seconds=(
                    record.get("session-max-lifetime-seconds")
                    if record.get("session-max-lifetime-seconds") is not None
                    else first_present(
                        params, "session-max-lifetime-seconds", "session_max_lifetime_seconds"
                    )
                ),
                # RV680: per-turn deadline and opt-in event-silence watchdog,
                # profile-param driven; None → runtime defaults, 0 disables.
                turn_timeout_seconds=first_present(
                    params, "session-turn-timeout-seconds", "session_turn_timeout_seconds"
                ),
                turn_silence_timeout_seconds=first_present(
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
                provider_metadata=session_store.session_provider_metadata(session_record),
            )
        else:
            # continue: the session must exist and be bound to the same profile
            if session_id is None:
                raise AudiaGenticError(
                    code="RES-AGW-002",
                    kind="agents",
                    message="gateway session id is missing",
                    details={"request-id": request_id},
                )
            session_id = str(session_id)
            session_record = session_store.read_session_record(project_root, session_id)
            if session_record["execution-profile-id"] != execution_profile_id:
                raise AudiaGenticError(
                    code="VAL-AGW-060",
                    kind="agents",
                    message="request execution profile does not match the session's profile",
                    details={
                        "session-id": session_id,
                        "session-profile": session_record["execution-profile-id"],
                        "request-profile": execution_profile_id,
                    },
                )
            # AS08/AS49: validate execution-context fingerprint exact match
            # only when the resolved provider surface declares that the
            # provider conversation is coupled to this gateway execution
            # context.  Persistent provider conversations (for example
            # GPT Auto's browser conversation) deliberately opt out through
            # SessionMappingFacts so a gateway restart/config reload does not
            # invalidate the durable provider session.  Resolution failure is
            # fail-closed: unknown surfaces retain the historical strict
            # fingerprint guard.
            requires_same_execution_context = True
            if context_fingerprint is not None:
                try:
                    current_surface = providers_api.resolve_session_surface(
                        project_root,
                        provider_id,
                        _build_surface_hint(profile),
                    )
                    requires_same_execution_context = bool(
                        current_surface.identity.mapping_facts.requires_same_execution_context
                    )
                except Exception:
                    logger.warning(
                        "could not resolve session surface mapping facts; enforcing execution fingerprint",
                        extra={"session-id": session_id, "provider-id": provider_id},
                        exc_info=True,
                    )

            if context_fingerprint is not None and requires_same_execution_context:
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
            # Handles are process-local. After a gateway restart the durable
            # record can remain active while its handle is absent. Reattach
            # the exact provider binding before applying continuation policy.
            if not runtime.session_runtime_status(session_id).get("available"):
                if (
                    session_record.get("state") == "closed"
                    and session_record.get("close-reason") == "shutdown"
                ):
                    # GP13 (scoped): transparently reattach rather than
                    # forcing the caller to detect RES-AGW-003 and
                    # separately call session_resume -- see
                    # _auto_resume_shutdown_closed_session's own docstring
                    # for why this is deliberately narrow. The resumed
                    # successor already has a live runtime handle (resume
                    # opens a real transport), so unlike the active-state
                    # branch below, no rehydrate_session() call follows.
                    session_id, session_record, record = _auto_resume_shutdown_closed_session(
                        project_root,
                        runtime,
                        source_session_id=session_id,
                        record=record,
                        context_fingerprint=context_fingerprint,
                        request_runtime_root=request_runtime_root,
                        project_name=project_name,
                    )
                elif session_record.get("state") != "active":
                    raise AudiaGenticError(
                        code="RES-AGW-003",
                        kind="agents",
                        message="session is not active and cannot be continued",
                        details=_terminal_session_diagnostics(session_id, session_record),
                    )
                else:
                    from audiagentic.components.providers import providers_api

                    opening_request_ids = session_store.session_request_ids(session_record)
                    rehydrate_root = (
                        gateway_request_dir(project_root, opening_request_ids[0]) / "runtime"
                        if opening_request_ids
                        else None
                    )
                    runtime.rehydrate_session(
                        project_root,
                        session_id,
                        execution_profile_id=execution_profile_id,
                        provider_id=provider_id,
                        model_id=session_store.session_model_id(session_record)
                        or record.get("resolved-model-id"),
                        surface_hint=_build_surface_hint(profile),
                        idle_timeout_seconds=(
                            record.get("session-idle-timeout-seconds")
                            if record.get("session-idle-timeout-seconds") is not None
                            else session_store.session_idle_timeout_seconds(session_record)
                        ),
                        max_lifetime_seconds=(
                            record.get("session-max-lifetime-seconds")
                            if record.get("session-max-lifetime-seconds") is not None
                            else session_store.session_max_lifetime_seconds(session_record)
                        ),
                        turn_timeout_seconds=first_present(
                            params, "session-turn-timeout-seconds", "session_turn_timeout_seconds"
                        ),
                        turn_silence_timeout_seconds=first_present(
                            params,
                            "session-turn-silence-timeout-seconds",
                            "session_turn_silence_timeout_seconds",
                        ),
                        correlation_id=record.get("correlation-id"),
                        request_runtime_root=rehydrate_root,
                        mcp_entries=providers_api.collect_management_mcp_launch_entries(project_root),
                        project_name=project_name,
                    )

            # Global/profile policy is applied only to the in-memory handle;
            # _SessionHandle.update_bounds keeps the more-open value.
            if record.get("session-keep-alive") and (
                record.get("session-idle-timeout-seconds") is not None
                or record.get("session-max-lifetime-seconds") is not None
            ):
                runtime.update_session_bounds(
                    session_id,
                    idle_timeout_seconds=record.get("session-idle-timeout-seconds"),
                    max_lifetime_seconds=record.get("session-max-lifetime-seconds"),
                )

        if session_id is None:
            raise AudiaGenticError(
                code="RES-AGW-002",
                kind="agents",
                message="gateway session was not established",
                details={"request-id": request_id},
            )
        session_id = str(session_id)
        _raise_if_cancelled(project_root, request_id)
        store.record_gateway_timeline(
            project_root,
            request_id,
            "attempt.started",
            state=store.read_record(project_root, request_id)["state"],
            attributes={
                "execution-profile-id": execution_profile_id,
                "provider-id": provider_id,
                "session-id": session_id,
                "attempt-index": 0,
                "max-attempts": 1,
            },
        )
        # The synchronous caller backstop derives from the session's durable
        # turn policy. A fixed ceiling can pre-empt a provider whose configured
        # response policy deliberately permits longer work. Zero disables both
        # the runtime deadline and this outer backstop.
        configured_turn_timeout = first_present(
            params, "session-turn-timeout-seconds", "session_turn_timeout_seconds"
        )
        if configured_turn_timeout is None:
            configured_turn_timeout = DEFAULT_TURN_TIMEOUT_SECONDS
        call_timeout = (
            float(configured_turn_timeout) + _TURN_CALL_GRACE_SECONDS
            if configured_turn_timeout
            else None
        )
        from audiagentic.components.agents.gateway.activity import RequestActivityRelay
        activity_relay = RequestActivityRelay(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            provider_capability="supported" if str(provider_id).startswith("gpt-auto") else "unknown",
        )
        result = runtime.prompt_in_session(
            project_root,
            session_id,
            dispatch_prompt,
            request_id=request_id,
            correlation_id=record.get("correlation-id"),
            timeout_seconds=call_timeout,
            activity_relay=activity_relay,
        )
    except _CancelledDuringDispatch:
        if request_runtime is not None:
            _cleanup_request_runtime(request_runtime)
        return _transition_owned_attempt(project_root, record, "cancelled")
    except AudiaGenticError as exc:
        if request_runtime is not None:
            _quarantine_request_runtime(request_runtime, request_runtime_root.parent / "quarantine")
        store.append_owned_attempt(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=record.get("resolved-model-id"),
            state="failed",
            error=exc,
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        return _transition_owned_attempt(
            project_root,
            record,
            "failed",
            updates={"error": exc, "session-id": session_id, "finished-at": now_iso_z()},
        )
    except BaseException as exc:
        # Safety net: wrap any non-AudiaGenticError so _redact_error preserves
        # the message (INT-AGW-098 boundary handler — prevents raw exceptions
        # like provider-specific errors from being silently redacted).
        logger.exception(
            "session dispatch failed with unhandled error",
            extra={"request-id": request_id},
        )
        if request_runtime is not None:
            _quarantine_request_runtime(request_runtime, request_runtime_root.parent / "quarantine")
        wrapped = AudiaGenticError(
            code="INT-AGW-098",
            kind="agents",
            message=f"session dispatch failed: {exc}",
            details={"original-type": type(exc).__name__},
        )
        store.append_owned_attempt(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=record.get("resolved-model-id"),
            state="failed",
            error=wrapped,
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        return _transition_owned_attempt(
            project_root,
            record,
            "failed",
            updates={"error": wrapped, "session-id": session_id, "finished-at": now_iso_z()},
        )

    # Freeze the last provider observation before terminal evidence/artifact
    # persistence. This is liveness evidence only; terminal state still owns
    # completion and cancellation decisions.
    try:
        activity_relay.observe_provider(
            source="session-transport",
            source_instance=f"session:{session_id}:turn:{request_id}",
            source_sequence=None,
            phase="finalizing",
            force=True,
        )
    except Exception:  # noqa: BLE001
        pass
    provider_metadata = dict(getattr(result, "metadata", {}) or {})
    if provider_metadata:
        record = store.update_owned_running_session(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            session_id=session_id,
            provider_metadata=provider_metadata,
        )

    if result.stop_reason == "cancelled":
        # RV680: a turn interrupted by protocol-level cancel is a cancelled
        # request, not a completed one. Preserve bounded result diagnostics so
        # operators can still see that the turn produced terminal evidence.
        session_record = session_store.read_session_record(project_root, session_id)
        model_id = session_store.session_model_id(session_record) or record.get("resolved-model-id")
        output_text = _session_output_from_result(result)
        store.append_owned_attempt(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            state="cancelled",
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        # Post-turn: close continued session if keep_alive=false and quiescent.
        if record.get("session-id") is not None and not record.get("session-keep-alive"):
            _post_turn_close_continued_session_if_quiescent(
                project_root,
                session_id,
                runtime,
            )
        if request_runtime is not None and not record.get("session-keep-alive"):
            _cleanup_request_runtime(request_runtime)
        return _transition_owned_attempt(
            project_root,
            record,
            "cancelled",
            updates={
                "provider-id": provider_id,
                "model-id": model_id,
                "output": output_text,
                "completion": {
                    "stop-reason": result.stop_reason,
                    "binding": binding_store.public_binding_projection(
                        session_record.get("binding")
                    ),
                    "total-events": result.observations_delivered + result.dropped_observations,
                    "dropped-events": result.dropped_observations,
                },
                "usage": None,
                "session-id": session_id,
                "finished-at": now_iso_z(),
            },
        )

    session_record = session_store.read_session_record(project_root, session_id)
    model_id = session_store.session_model_id(session_record) or record.get("resolved-model-id")
    output_text = _session_output_from_result(result)
    from audiagentic.components.agents.gateway.output import persist_final_response
    artifact = persist_final_response(project_root, request_id, output_text)
    artifact_ref = {key: artifact[key] for key in ("artifact-id", "request-id", "media-type", "bytes", "sha256")}
    store.append_owned_attempt(
        project_root,
        request_id,
        owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
        execution_profile_id=execution_profile_id,
        provider_id=provider_id,
        model_id=model_id,
        state="completed",
        started_at=started_at,
        finished_at=now_iso_z(),
    )
    # Post-turn: close continued session if keep_alive=false and quiescent.
    if record.get("session-id") is not None and not record.get("session-keep-alive"):
        _post_turn_close_continued_session_if_quiescent(
            project_root,
            session_id,
            runtime,
        )
    if request_runtime is not None and not record.get("session-keep-alive"):
        _cleanup_request_runtime(request_runtime)
    return _transition_owned_attempt(
        project_root,
        record,
        "completed",
        updates={
            "provider-id": provider_id,
            "model-id": model_id,
            "output": output_text,
            "response-artifact": artifact_ref,
            "output-preview": artifact["output-preview"],
            "output-truncated": artifact["output-truncated"],
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


def _cleanup_request_runtime(runtime_root: Path) -> None:
    import shutil

    try:
        shutil.rmtree(runtime_root, ignore_errors=True)
    except OSError:
        logger.warning("failed to clean up session request runtime", exc_info=True)


def _quarantine_request_runtime(runtime_root: Path, quarantine_root: Path) -> Path:
    import shutil

    destination = quarantine_root / runtime_root.parent.name
    # Some session transports do not materialize a request runtime. A provider
    # failure must retain its own error instead of being replaced by a cleanup
    # FileNotFoundError for an optional directory.
    if not runtime_root.exists():
        return destination
    quarantine_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            shutil.rmtree(destination)
        except OSError:
            logger.warning("failed to remove stale session runtime quarantine", exc_info=True)
            raise
    try:
        shutil.move(str(runtime_root), str(destination))
    except OSError:
        logger.warning("failed to quarantine session request runtime", exc_info=True)
        raise
    return destination


def _get_stored_context_fingerprint(session_record: dict[str, Any]) -> str | None:
    binding = session_record.get("binding")
    if not isinstance(binding, dict):
        return None
    value = binding.get("execution-context-fingerprint")
    return value if isinstance(value, str) and value else None


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
