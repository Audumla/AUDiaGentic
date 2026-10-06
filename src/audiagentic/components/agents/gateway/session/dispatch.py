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
import hashlib
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import SessionFailureDisposition

logger = logging.getLogger(__name__)


def _merge_provider_metadata(
    current_metadata: dict[str, Any] | None,
    request_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Merge provider metadata without destroying unresolved-turn evidence.

    A pre-send fence is deliberately ``submission-proven=False``.  It still
    carries the prompt text digest used to correlate a completed DOM turn when
    ChatGPT does not expose message ids.  The old merge removed that digest
    along with provider ids, leaving the durable unresolved marker with no
    recovery evidence and causing an endless presubmit-reconcile loop.
    """
    merged = dict(current_metadata) if isinstance(current_metadata, dict) else {}
    # Only an explicit false is a pre-send/unproven fence.  Provider
    # metadata relays are allowed to omit this field; omission must not erase
    # correlation or terminal evidence already persisted for the turn.
    if request_metadata.get("submission-proven") is False:
        for key in (
            "prompt-message-id",
            "assistant-message-id",
            "assistant-before-message-id",
            "assistant-before-id",
            "submission-proven",
            "prompt-text-digest",
            "terminal-evidence",
        ):
            merged.pop(key, None)
    merged.update(request_metadata)
    return merged


_UNRESOLVED_CHECKPOINT_KEYS = (
    "unresolved-turn-id",
    "prompt-message-id",
    "assistant-message-id",
    "assistant-before-message-id",
    "assistant-before-id",
    "prompt-text-digest",
    "submission-proven",
    "terminal-evidence",
)


def _clear_terminal_predecessor_fence(
    project_root: Path,
    record: dict[str, Any],
    *,
    session_store: Any,
) -> dict[str, Any] | None:
    """Clear only a proven stale predecessor fence before a new prompt."""
    metadata = record.get("provider-metadata")
    if not isinstance(metadata, dict) or metadata.get("unresolved-turn-pending") is not True:
        return None
    predecessor_id = metadata.get("unresolved-turn-id")
    if not isinstance(predecessor_id, str) or not predecessor_id or predecessor_id == record.get("request-id"):
        return None
    try:
        predecessor = store.read_record(project_root, predecessor_id)
    except AudiaGenticError:
        return None
    if predecessor.get("state") not in {"failed", "cancelled", "interrupted", "completed"}:
        return None
    error = predecessor.get("error")
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, dict):
        return None
    dom_signals = set(details.get("dom-signals") or ())
    if not details.get("failure-response-available") or "completion-control" not in dom_signals:
        return None
    session_id = record.get("session-id")
    if not isinstance(session_id, str) or not session_id:
        return None
    cleared = dict(metadata)
    cleared["unresolved-turn-pending"] = False
    cleared["recovery-state"] = "stale-predecessor-fence-cleared"
    cleared["stale-predecessor-request-id"] = predecessor_id
    for key in _UNRESOLVED_CHECKPOINT_KEYS:
        cleared.pop(key, None)
    session_store.update_provider_metadata(
        project_root, session_id,
        {"unresolved-turn-pending": False, "recovery-state": "stale-predecessor-fence-cleared", "stale-predecessor-request-id": predecessor_id},
        remove_keys=_UNRESOLVED_CHECKPOINT_KEYS,
    )
    updated = store.update_owned_running_session(
        project_root, record["request-id"],
        owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
        session_id=session_id,
        provider_metadata=cleared,
    )
    store.record_gateway_timeline(
        project_root, record["request-id"],
        "provider.unresolved-fence-cleared",
        state=updated["state"],
        attributes={
            "predecessor-request-id": predecessor_id,
            "predecessor-state": predecessor.get("state"),
            "reason": "terminal-predecessor-with-completion-control-and-failure-response",
        },
    )
    return updated

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


def _explain_stale_session_runtime_error(
    project_root: Path,
    session_id: str,
    error: AudiaGenticError,
) -> AudiaGenticError:
    """Turn the process-local stale-session error into actionable evidence.

    A durable provider session can survive a gateway restart while its
    in-memory transport handle does not. The old ``RES-AGW-003`` text made
    that look like a provider failure and did not tell callers whether their
    prompt had reached the provider. Keep the stable code, but add a narrow
    explanation only for the exact process-local handle miss.
    """
    if error.code != "RES-AGW-003" or "not active in this gateway process" not in error.message:
        return error

    details = dict(error.details or {})
    details.update(
        {
            "failure-reason": "stale-session-runtime",
            "runtime-state": "non-live",
            "prompt-submission": "not-started",
            "recovery-action": "retry-continuation-to-rehydrate-session",
        }
    )
    try:
        from audiagentic.components.agents.gateway.session import sessions_store

        persisted = sessions_store.read_session_record(project_root, session_id)
        details.update(
            {
                "durable-session-state": persisted.get("state"),
                "durable-session-retained": True,
                "provider-binding-retained": bool(
                    isinstance(persisted.get("binding"), dict)
                    and persisted["binding"].get("provider-session-ref")
                ),
            }
        )
        details.update(
            {
                key: value
                for key, value in _terminal_session_diagnostics(session_id, persisted).items()
                if key not in details
            }
        )
    except Exception:  # noqa: BLE001 - diagnostics must never mask the original failure
        details["durable-session-retained"] = False

    return AudiaGenticError(
        code=error.code,
        kind=error.kind,
        message=(
            "durable provider session is not attached to this gateway process; "
            "no prompt was submitted"
        ),
        details=details,
    )


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


_AUTO_RESUMABLE_CLOSE_REASONS = frozenset({"shutdown", "idle-timeout"})


def _auto_resume_reopenable_closed_session(
    project_root: Path,
    runtime: Any,
    *,
    source_session_id: str,
    record: dict[str, Any],
    context_fingerprint: str | None,
    request_runtime_root: Path,
    project_name: str | None = None,
    allow_failed: bool = False,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Transparently resume a session closed by a resumable gateway policy.

    Reproduced live 2026-08-17: a force gateway restart (loading unrelated
    fixes) explicitly closed every live session machine-wide
    (close-reason=shutdown) as part of its own stop sequence. A concurrent
    caller's next continuation against one of those sessions got a hard
    RES-AGW-003 even though the closed record still carried everything
    needed to resume the same live provider conversation. Deliberately
    narrow in scope: a gateway shutdown and its configured ``idle-timeout``
    are resource-lifetime policies, not evidence that the provider
    conversation is invalid. A later turn may therefore resume the durable
    provider binding. A failed source is accepted only for the
    observation-only restart-recovery path (``allow_failed=True``); ordinary
    continuation still requires an explicit session_resume.

    Reuses AS49's existing resume_session() machinery.  The runtime now
    serializes the complete source-to-successor decision per source session;
    the deterministic control id still makes repeated automatic recovery
    idempotent, while the lock also closes the race with an explicit resume
    using a different control id.

    Returns (new_session_id, new_session_record, updated_request_record).
    Raises the original RES-AGW-003 for any expected resume-ineligibility
    refusal (see _AUTO_RESUME_EXPECTED_REFUSAL_CODES); any other error
    (a lost ownership fence, a store failure, an internal resume defect)
    propagates as itself -- it must never be masked as mere ineligibility.
    """
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    recovery = record.get("recovery")
    recovery_attempt = recovery.get("attempt", 0) if isinstance(recovery, dict) else 0
    try:
        recovery_attempt = max(0, int(recovery_attempt))
    except (TypeError, ValueError):
        recovery_attempt = 0

    def _resume_control_id(resume_source: str) -> str:
        # A failed observation-only control must not permanently poison all
        # later attempts for the same source. Each durable recovery attempt
        # gets its own idempotency key; ordinary explicit/resource-policy
        # resumes retain the stable source-scoped key.
        suffix = f":observation:{recovery_attempt}" if allow_failed else ""
        return f"auto-resume:{resume_source}{suffix}"

    if allow_failed:
        logger.info(
            "resuming failed local session as an observation-only restart successor",
            extra={"source-session-id": source_session_id, "request-id": record.get("request-id")},
        )

    try:
        resume_source_id = source_session_id
        new_session_record = runtime.resume_session(
            project_root,
            resume_source_id,
            # Deterministic, not request-scoped: two concurrent
            # continuations against the SAME closed source must resolve to
            # the same idempotency lookup, which a request-id-derived key
            # would not give them.
            control_id=_resume_control_id(resume_source_id),
            execution_context_fingerprint=context_fingerprint or record.get("context-fingerprint"),
            request_runtime_root=request_runtime_root,
            project_name=project_name,
            resume_existing=allow_failed,
        )
        # A later gateway shutdown can close the idempotent successor before
        # the next caller arrives. Replaying the original control then
        # returns that same terminal successor forever. Walk a bounded chain
        # of resumable shutdown generations, preserving idempotency per
        # generation and never opening an unrelated fresh conversation.
        for _ in range(3):
            # The provider/runtime may close the returned successor during
            # shutdown immediately after resume_session returns; refresh the
            # durable record before deciding whether it is usable.
            try:
                new_session_record = session_store.read_session_record(
                    project_root, str(new_session_record["session-id"])
                )
            except Exception:
                pass
            if new_session_record.get("state") not in {"closed", "expired"}:
                break
            if new_session_record.get("close-reason") not in _AUTO_RESUMABLE_CLOSE_REASONS:
                break
            resume_source_id = str(new_session_record["session-id"])
            new_session_record = runtime.resume_session(
                project_root,
                resume_source_id,
                control_id=_resume_control_id(resume_source_id),
                execution_context_fingerprint=context_fingerprint or record.get("context-fingerprint"),
                request_runtime_root=request_runtime_root,
                project_name=project_name,
                resume_existing=allow_failed,
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
        "gateway session transparently resumed after resumable closure",
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


def _session_output_media_type(result: Any) -> str:
    value = getattr(result, "final_media_type", None)
    return value if isinstance(value, str) and value else "text/plain; charset=utf-8"

def _session_output_from_result(result: Any) -> str | None:
    """Read the bounded final summary from a SessionTurnResult.

    Output is produced inside the ACP adapter; agents never reconstructs
    output from protocol events. The adapter carries assistant-text
    fragments only (no thought, tool args, provider refs)."""
    return result.final_summary if hasattr(result, "final_summary") else None


def _failure_response_updates(project_root: Path, request_id: str, error: Any) -> dict[str, Any]:
    """Persist provider DOM text separately from successful request output."""
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return {}
    text = details.get("failure-response-text")
    if not isinstance(text, str) or not text.strip():
        return {}
    from audiagentic.components.agents.gateway.output import persist_failure_response

    artifact = persist_failure_response(project_root, request_id, text)
    return {
        "failure-response-artifact": {
            key: artifact[key]
            for key in ("artifact-id", "request-id", "media-type", "bytes", "sha256")
        },
        "failure-response-preview": artifact["output-preview"],
        "failure-response-truncated": artifact["output-truncated"],
    }


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
    _default_recovery_attempt: int = 0,
    _network_followup_attempts: int = 0,
    _provider_error_followup_attempts: int = 0,
    _unsent_retry_used: bool = False,
    session_start: Any | None = None,
    project_name: str | None = None,
    resume_existing: bool = False,
) -> dict[str, Any]:
    """Dispatch a sessionful request through the live SessionRuntime (AS04).

    Stateful sends are not replayed without proof. A composer timeout with
    explicit provider proof that Send was never reached gets one same-session
    retry; exhaustion preserves the default and terminalizes only the request.

    The admitted prompt is passed separately from the public record. Session
    dispatch receives the frozen semantic payload and never re-reads mutable
    prompt/config sources.
    """
    from audiagentic.components.agents.agents_paths import gateway_request_dir
    from audiagentic.components.agents.gateway import profiles as profiles_mod
    from audiagentic.components.agents.gateway.session import bindings as binding_store
    from audiagentic.components.agents.gateway.session import sessions_store as session_store
    from audiagentic.components.agents.gateway.session.sessions import get_session_runtime
    from audiagentic.components.providers import providers_api

    request_id = record["request-id"]
    execution_profile_id = record["execution-profile-id"]
    recovery = record.get("recovery")
    recovery = recovery if isinstance(recovery, dict) else {}
    continuation = recovery.get("continuation")
    continuation = continuation if isinstance(continuation, dict) else {}
    # A follow-up prompt is a provider-side continuation, not a fresh root
    # dispatch.  The queue may invoke this runner again after the provider
    # adapter lost its observation handle; restore the durable counters and
    # force observation-only recovery so the original prompt is never replayed.
    if recovery.get("phase") == "followup-reconcile" and continuation:
        resume_existing = True
        try:
            _network_followup_attempts = max(
                _network_followup_attempts,
                int(continuation.get("network-followup-attempts", 0)),
            )
            _provider_error_followup_attempts = max(
                _provider_error_followup_attempts,
                int(continuation.get("provider-error-followup-attempts", 0)),
            )
            _default_recovery_attempt = max(
                _default_recovery_attempt,
                int(continuation.get("default-recovery-attempt", 0)),
            )
        except (TypeError, ValueError):
            # Invalid private recovery metadata must not make the request
            # eligible for a new prompt.  Observation-only recovery remains
            # the safe default.
            resume_existing = True
    runtime = get_session_runtime()
    project_name = project_name or _admitted_project_name(record)

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
        from audiagentic.components.agents.configuration.global_catalog import (
            resolve_global_execution_profile as resolve_execution_profile,
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
    from audiagentic.components.agents.gateway.session import client_defaults
    preparation_guard = client_defaults.preparation_guard(record)
    preparation_guard.acquire()
    guard_held = True
    runtime_invoked = False
    try:
        if not isinstance(dispatch_prompt, str) or not dispatch_prompt.strip():
            # A restart can lose the private admitted-prompt snapshot after
            # the provider has already answered. Before retaining the
            # request in an endless rehydrate retry, use the same
            # evidence-gated DOM capture exposed to operators. It can only
            # terminalize after proving a stable, request-owned response, so
            # an incomplete or ambiguous turn remains in observation-only
            # recovery and is never replayed.
            if resume_existing:
                try:
                    from audiagentic.components.agents.gateway.api import (
                        complete_execution_from_provider,
                    )
                    captured = complete_execution_from_provider(project_root, request_id)
                except Exception:  # noqa: BLE001 - incomplete turns remain recoverable
                    captured = None
                if isinstance(captured, dict) and captured.get("state") in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    return store.read_record(project_root, request_id)
                # Restart recovery deliberately has no prompt to replay. If
                # the current provider DOM was not already terminal, continue
                # into the observation-only resume_existing path below. The
                # provider transport owns the durable unresolved-turn
                # checkpoint and must be allowed to reattach it.
            else:
                raise AudiaGenticError(
                    code="RES-AGW-004",
                    kind="agents",
                    message="admitted request has no recoverable dispatch prompt",
                    details={
                        "failure-reason": "dispatch-prompt-unavailable",
                        "resume-existing": resume_existing,
                        "request-id": request_id,
                    },
                )
        if not resume_existing:
            record = client_defaults.redirect_if_replaced(project_root, record)
        session_id = record.get("session-id")
        if session_id is None:
            raise AudiaGenticError(
                code="RES-AGW-002",
                kind="agents",
                message="admitted request is missing its durable gateway session",
                details={"request-id": request_id},
            )
        session_id = str(session_id)
        admitted_session = session_store.read_session_record(project_root, session_id)
        if admitted_session.get("provider-transport-kind") != "provider-session":
            raise AudiaGenticError(
                code="CON-AGW-122",
                kind="agents",
                message="worker-backed request was routed to provider-session dispatch",
                details={"request-id": request_id, "session-id": session_id},
            )
        is_new_session = admitted_session.get("created-by-request-id") == request_id
        if record.get("client-default-session"):
            is_new_session = not admitted_session.get("binding") and not runtime.session_runtime_status(session_id).get("available")
        if resume_existing:
            # Recovery must never use the request-creator fast path.  That
            # path opens a fresh provider transport and can lose the durable
            # session binding/checkpoint when the request-level relay was
            # interrupted before publication.
            is_new_session = False

        async def _relay_provider_metadata(metadata: dict[str, Any]) -> None:
            nonlocal record
            merged_metadata = _merge_provider_metadata(
                record.get("provider-metadata"), dict(metadata)
            )
            record = store.update_owned_running_session(
                project_root,
                request_id,
                owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"],
                session_id=session_id,
                provider_metadata=merged_metadata,
            )
            client_defaults.remember(project_root, record)

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
            provider_chat_url = None
            request_metadata = record.get("metadata")
            if isinstance(request_metadata, dict):
                candidate_url = request_metadata.get("provider-chat-url")
                if isinstance(candidate_url, str) and candidate_url:
                    provider_chat_url = candidate_url
            resume_provider_ref = None
            resume_provider_metadata = None
            if provider_chat_url is not None:
                from audiagentic.components.providers.adapters.gpt_auto.urls import (
                    parse_provider_session_id,
                )

                resume_provider_ref = parse_provider_session_id(provider_chat_url)
                resume_provider_metadata = {"chat-url": provider_chat_url}
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
                model_selector=record.get("resolved-model-selector"),
                project_name=project_name,
                request_provider_metadata_sink=_relay_provider_metadata,
                resume_provider_ref=resume_provider_ref,
                resume_provider_metadata=resume_provider_metadata,
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
            # The client-default guard protects selection/binding, not the
            # potentially slow provider rehydration operation.  Holding it
            # while CDP/browser recovery runs can strand a later request for
            # the same client before it reaches the session turn lock or its
            # activity watcher.  The durable session/turn fences below own
            # concurrency once this request has selected its session.
            if guard_held:
                preparation_guard.release()
                guard_held = False
            # Handles are process-local. After a gateway restart the durable
            # record can remain active while its handle is absent. Reattach
            # the exact provider binding before applying continuation policy.
            if not runtime.session_runtime_status(session_id).get("available"):
                if (
                    not resume_existing
                    and session_record.get("state") in {"closed", "expired"}
                    and session_record.get("close-reason") in _AUTO_RESUMABLE_CLOSE_REASONS
                ):
                    # A gateway resource-policy close retains the durable
                    # provider binding. Resume creates one linked successor
                    # with a live transport, so no active-state rehydrate is
                    # needed here. Intentional close and failure reasons are
                    # deliberately excluded from this automatic path.
                    session_id, session_record, record = _auto_resume_reopenable_closed_session(
                        project_root,
                        runtime,
                        source_session_id=session_id,
                        record=record,
                        context_fingerprint=context_fingerprint,
                        request_runtime_root=request_runtime_root,
                        project_name=project_name,
                    )
                elif resume_existing and session_record.get("state") == "failed":
                    session_id, session_record, record = _auto_resume_reopenable_closed_session(
                        project_root,
                        runtime,
                        source_session_id=session_id,
                        record=record,
                        context_fingerprint=context_fingerprint,
                        request_runtime_root=request_runtime_root,
                        project_name=project_name,
                        allow_failed=True,
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
                    try:
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
                            resume_existing=resume_existing,
                        )
                    except AudiaGenticError as exc:
                        if exc.code == "EXT-AGW-118":
                            # Rehydration itself is observation-only.  This is
                            # true both before a fresh prompt and while
                            # recovering an already-submitted turn: opening
                            # the exact retained conversation may fail because
                            # the CDP bridge/browser is transiently unavailable,
                            # but that cannot prove the provider turn stopped
                            # or that the prompt was unsent.  Keep the same
                            # request/session in recovery for either path;
                            # never rotate the client default or replay a
                            # prompt merely because reattachment was refused.
                            raise RecoveryDeferred(
                                exc,
                                phase="rehydrate-retry",
                                side_effect_state=(
                                    "may-have-started" if resume_existing else "not-started"
                                ),
                            ) from exc
                        raise

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
                    **({"replace_idle_timeout": True} if str(provider_id).startswith("gpt-auto") else {}),
                )

        if session_id is None:
            raise AudiaGenticError(
                code="RES-AGW-002",
                kind="agents",
                message="gateway session was not established",
                details={"request-id": request_id},
            )
        session_id = str(session_id)
        if resume_existing and store.read_record(project_root, request_id).get("cancel-requested"):
            # Recovered work may already have sent this turn. Reattach first,
            # signal cancellation against the exact turn, and let the
            # provider resume path establish the authoritative outcome.
            runtime.request_cancel(request_id, session_id=session_id)
        else:
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
        from audiagentic.components.agents.gateway.activity import RequestActivityRelay
        activity_relay = RequestActivityRelay(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            provider_capability="supported" if str(provider_id).startswith("gpt-auto") else "unknown",
        )
        client_defaults.remember(project_root, record)
        if guard_held:
            preparation_guard.release()
            guard_held = False
        # This only proves that SessionRuntime was entered.  Provider
        # submission state comes from the transport's typed failure contract.
        runtime_invoked = True
        dispatch_claim = None
        if session_start is not None and store.read_record(project_root, request_id)["state"] == "queued":
            def _claim_session_turn() -> dict[str, Any]:
                nonlocal record
                record = session_start()
                return record

            dispatch_claim = _claim_session_turn
        result = runtime.prompt_in_session(
            project_root,
            session_id,
            dispatch_prompt,
            request_id=request_id,
            correlation_id=record.get("correlation-id"),
            # Provider activity renews the durable request lease. An outer
            # elapsed-time deadline here would cancel an otherwise healthy
            # turn immediately before its terminal event reaches us.
            timeout_seconds=None,
            activity_relay=activity_relay,
            dispatch_claim=dispatch_claim,
            resume_existing=resume_existing,
            request_provider_metadata_sink=_relay_provider_metadata,
        )
    except _CancelledDuringDispatch:
        if guard_held:
            preparation_guard.release()
        if resume_existing:
            raise RecoveryDeferred(
                AudiaGenticError(
                    code="CON-AGW-CANCELLED",
                    kind="agents",
                    message="recovered turn cancellation requires provider reconciliation",
                    details={"session-id": session_id, "request-id": request_id},
                ),
                phase="cancel-reconcile",
            )
        if request_runtime is not None:
            _cleanup_request_runtime(request_runtime)
        return _transition_owned_attempt(project_root, record, "cancelled")
    except RecoveryDeferred:
        # RecoveryDeferred is queue control flow, not a terminal provider
        # error. Preserve it so the queue can retain the running request and
        # schedule the next exact-session rehydration attempt.
        if guard_held:
            preparation_guard.release()
        raise
    except AudiaGenticError as exc:
        if guard_held:
            preparation_guard.release()
        if resume_existing:
            disposition = runtime.session_failure_disposition(session_id)
            if disposition is not SessionFailureDisposition.TERMINAL_FAILED:
                # Rehydrate/open failures cannot prove that the old generation
                # did not submit the turn. The queue owns the non-terminal
                # retry and keeps the durable request/session identity.
                followup_recovery = recovery.get("phase") == "followup-reconcile"
                raise RecoveryDeferred(
                    exc,
                    phase=(
                        "followup-reconcile"
                        if followup_recovery
                        else ("rehydrate-retry" if not runtime_invoked else "observe-retry")
                    ),
                    continuation=continuation if followup_recovery else None,
                ) from exc
        cancelled = store.read_record(project_root, request_id).get("cancel-requested")
        if (
            client_defaults.structured_presubmit_failure(exc)
            and (exc.details or {}).get("previous-turn-unresolved") is True
            and not cancelled
        ):
            # A terminal predecessor with captured completion evidence cannot
            # keep the session fenced forever. Clear only that proven stale
            # checkpoint; live or ambiguous predecessors remain queued safely.
            cleared = _clear_terminal_predecessor_fence(
                project_root,
                store.read_record(project_root, request_id),
                session_store=session_store,
            )
            if cleared is not None:
                return _dispatch_session_request(
                    project_root,
                    cleared,
                    dispatch_prompt=dispatch_prompt,
                    context_fingerprint=context_fingerprint,
                    _default_recovery_attempt=_default_recovery_attempt,
                    _network_followup_attempts=_network_followup_attempts,
                    _provider_error_followup_attempts=_provider_error_followup_attempts,
                    _unsent_retry_used=_unsent_retry_used,
                    session_start=session_start,
                    project_name=project_name,
                    resume_existing=False,
                )            # The current prompt was never submitted, but the preceding
            # provider turn still has an unresolved Send fence.  Keep this
            # request queued on the same session until reconciliation proves
            # the session safe; never replay it or rotate the client's default.
            raise RecoveryDeferred(
                exc,
                phase="presubmit-reconcile",
                side_effect_state="not-started",
            ) from exc
        if client_defaults.proven_same_session_presubmit_retryable_failure(exc) and not cancelled and not _unsent_retry_used:
            store.append_owned_attempt(
                project_root, request_id, owner_epoch=record["dispatch-owner-epoch"],
                worker_id=record["worker-id"], attempt_epoch=record["attempt-epoch"],
                execution_profile_id=execution_profile_id, provider_id=provider_id,
                model_id=record.get("resolved-model-id"), state="failed", error=exc,
                started_at=started_at, finished_at=now_iso_z(),
            )
            # The provider has explicitly proved Send was never reached.
            # Retry once on the same handle, never rotate the default; all
            # unknown/post-send failures continue through conservative recovery.
            return _dispatch_session_request(
                project_root, record, dispatch_prompt=dispatch_prompt,
                context_fingerprint=context_fingerprint,
                _default_recovery_attempt=_default_recovery_attempt,
                _unsent_retry_used=True,
                session_start=session_start,
                resume_existing=resume_existing,
            )
        if (
            not cancelled
            and isinstance(exc.details, dict)
            and exc.details.get("failure-stage") == "submission"
            and exc.details.get("submission-state") == "not_started"
            and exc.details.get("submission-ambiguous") is False
        ):
            # A browser admission failure proved that Send was never reached.
            # Keep the request queued for bounded provider recovery instead of
            # rotating or terminalizing it; retrying remains safe because the
            # durable unresolved fence was cleared by the transport.
            raise RecoveryDeferred(
                exc,
                phase="presubmit-retry",
                side_effect_state="not-started",
            ) from exc
        if not resume_existing and not store.read_record(project_root, request_id).get("cancel-requested"):
            failure_details = exc.details if isinstance(exc.details, dict) else {}
            dom_signals = failure_details.get("dom-signals") or ()
            recovery_policy = failure_details.get("recovery-policy")
            if not isinstance(recovery_policy, dict):
                # Compatibility for older provider records that predate the
                # workflow recovery block. Resolved current configs always
                # provide this policy through the adapter diagnostics.
                recovery_policy = {
                    "network-error-followup-enabled": True,
                    "network-error-followup-max-attempts": 1,
                    "network-error-followup-prompt-template": (
                        "Complete the previous request. The previous response was interrupted by a "
                        "network error. Continue from the work already done and provide the complete "
                        "answer.\n\nOriginal request:\n{original_request}"
                    ),
                    "provider-error-followup-enabled": True,
                    "provider-error-followup-max-attempts": 1,
                    "provider-error-followup-prompt-template": (
                        "Complete the previous request. ChatGPT reported a temporary request error. "
                        "Continue from the work already done and provide the complete "
                        "answer.\n\nOriginal request:\n{original_request}"
                    ),
                    "conversation-load-failure-recovery-enabled": True,
                    "conversation-load-failure-max-attempts": 2,
                }
            load_failed = (
                failure_details.get("failure-reason") == "conversation-load-failed"
                or "conversation-load-failed" in dom_signals
            )
            # A conversation-load error is safe to recover in a fresh chat
            # only when the failed page proves that this request never got
            # past submission.  Once Send was proven, or submission remains
            # ambiguous, rotating the session and replaying the original
            # prompt can duplicate provider work that is still running in the
            # old conversation.  Preserve the current session/evidence and
            # let the normal terminal/recovery policy decide its outcome.
            load_submission_proven = failure_details.get("submission-proven") is True
            # Fresh-session replay is safe only with affirmative proof that
            # this request never crossed the browser side-effect boundary.
            # Missing fields are intentionally unsafe: older or incomplete
            # failure producers must not turn a conversation-load error into
            # a duplicate provider prompt.
            load_proven_unsent = (
                failure_details.get("submission-proven") is False
                and failure_details.get("submission-ambiguous") is False
                and (
                    failure_details.get("submission-attempted") is False
                    or (
                        failure_details.get("failure-stage") == "submission"
                        and failure_details.get("submission-state") == "not_started"
                    )
                )
            )
            load_submission_ambiguous = (
                not load_proven_unsent
                if load_failed
                else failure_details.get("submission-ambiguous") is True
            )
            load_recovery_enabled = bool(
                recovery_policy.get("conversation-load-failure-recovery-enabled", True)
            )
            try:
                load_recovery_max_attempts = max(
                    0,
                    int(recovery_policy.get("conversation-load-failure-max-attempts", 2)),
                )
                network_followup_max_attempts = max(
                    0,
                    int(recovery_policy.get("network-error-followup-max-attempts", 1)),
                )
                provider_error_followup_max_attempts = max(
                    0,
                    int(recovery_policy.get("provider-error-followup-max-attempts", 1)),
                )
            except (TypeError, ValueError):
                load_recovery_max_attempts = 0
                network_followup_max_attempts = 0
                provider_error_followup_max_attempts = 0
            if load_failed and not load_proven_unsent:
                # A load-error page is not proof that the provider turn
                # stopped.  Once submission is proven, ambiguous, or simply
                # undocumented by an older failure producer, retain the
                # request/session and re-enter observation-only recovery.
                # Falling through to the terminal failure transition here
                # strands provider work and breaks FIFO continuation after a
                # gateway restart.
                failure_updates = _failure_response_updates(project_root, request_id, exc)
                if failure_updates:
                    record = store.update_owned_running_session(
                        project_root,
                        request_id,
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                        session_id=session_id,
                        result_updates=failure_updates,
                    )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "provider.conversation.load-observation-deferred",
                    state="running",
                    attributes={
                        "same-session": True,
                        "submission-proven": load_submission_proven,
                        "submission-ambiguous": load_submission_ambiguous,
                        "failure-response-available": bool(failure_updates),
                    },
                )
                raise RecoveryDeferred(
                    exc,
                    phase="conversation-load-reconcile",
                    side_effect_state="may-have-started",
                    continuation={
                        "kind": "conversation-load",
                        "resume-existing": True,
                        "default-recovery-attempt": _default_recovery_attempt,
                        "load-recovery-attempts": _default_recovery_attempt + 1,
                    },
                ) from exc
            if (
                load_failed
                and load_recovery_enabled
                and _default_recovery_attempt < load_recovery_max_attempts
                and load_proven_unsent
            ):
                replacement = client_defaults.replace_failed_default(
                    project_root, record, exc, recover_url=False, attach_request=True,
                )
                if replacement is None:
                    replacement = client_defaults.replace_failed_session(project_root, record, exc)
                if replacement is not None:
                    return _dispatch_session_request(
                        project_root, replacement, dispatch_prompt=dispatch_prompt,
                        context_fingerprint=context_fingerprint,
                        _default_recovery_attempt=_default_recovery_attempt + 1,
                        session_start=session_start,
                        resume_existing=False,
                    )
            network_followup_enabled = bool(
                recovery_policy.get("network-error-followup-enabled", True)
            )
            network_observation_only = (
                "network-error-alert" in dom_signals
                and runtime_invoked
                and (
                    not network_followup_enabled
                    or _network_followup_attempts >= network_followup_max_attempts
                )
            )
            if (
                "network-error-alert" in dom_signals
                and (
                    (
                        network_followup_enabled
                        and _network_followup_attempts < network_followup_max_attempts
                    )
                    or network_observation_only
                )
                and runtime_invoked
                and runtime.session_failure_disposition(session_id)
                is not SessionFailureDisposition.TERMINAL_FAILED
            ):
                # The original Send may have reached the provider. Preserve
                # the evidence and defer to observation or explicit recovery;
                # never submit a second prompt from an ambiguous failure.
                failure_updates = _failure_response_updates(project_root, request_id, exc)
                if failure_updates:
                    record = store.update_owned_running_session(
                        project_root,
                        request_id,
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                        session_id=session_id,
                        result_updates=failure_updates,
                    )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "provider.turn.failure-recovered",
                    state="running",
                    attributes={
                        "reason": "network-error-alert",
                        "same-session": True,
                        "original-prompt-length": len(dispatch_prompt),
                        "followup-attempt": _network_followup_attempts + 1,
                        "recovery-mode": (
                            "observation-only" if network_observation_only else "followup-reconcile"
                        ),
                        "failure-response-available": bool(failure_updates),
                        "dom-signals": sorted(str(item) for item in (failure_details.get("dom-signals") or ())),
                        "observed-assistant-id": failure_details.get("failure-response-message-id"),
                        "activity-sequence": failure_details.get("activity-sequence"),
                    },
                )
                raise RecoveryDeferred(
                    exc,
                    phase="followup-reconcile",
                    side_effect_state="may-have-started",
                    continuation={
                        "kind": "network-error-observation",
                        "resume-existing": True,
                        "network-followup-attempts": _network_followup_attempts,
                        "default-recovery-attempt": _default_recovery_attempt,
                        "failure-response-available": bool(failure_updates),
                    },
                ) from exc
            error_evidence = {
                str(signal)
                for signal in (*dom_signals, *(failure_details.get("evidence") or ()))
            }
            provider_error_alert = bool(
                error_evidence.intersection(
                    {"request-error-alert", "error-alert", "stream-cache-expired"}
                )
            )
            provider_followup_enabled = bool(
                recovery_policy.get("provider-error-followup-enabled", True)
            )
            provider_observation_only = (
                provider_error_alert
                and runtime_invoked
                and (
                    not provider_followup_enabled
                    or _provider_error_followup_attempts >= provider_error_followup_max_attempts
                )
            )
            if (
                provider_error_alert
                and "network-error-alert" not in error_evidence
                and (
                    (
                        provider_followup_enabled
                        and _provider_error_followup_attempts < provider_error_followup_max_attempts
                    )
                    or provider_observation_only
                )
                and runtime_invoked
                and runtime.session_failure_disposition(session_id)
                is not SessionFailureDisposition.TERMINAL_FAILED
            ):
                # A provider alert is not proof that Send was never reached.
                # Preserve the failed attempt and require observation or an
                # explicit recovery action before any new provider prompt.
                failure_updates = _failure_response_updates(project_root, request_id, exc)
                if failure_updates:
                    record = store.update_owned_running_session(
                        project_root,
                        request_id,
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                        session_id=session_id,
                        result_updates=failure_updates,
                    )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "provider.turn.failure-recovered",
                    state="running",
                    attributes={
                        "reason": "provider-error-alert",
                        "same-session": True,
                        "original-prompt-length": len(dispatch_prompt),
                        "followup-attempt": _provider_error_followup_attempts + 1,
                        "recovery-mode": (
                            "observation-only" if provider_observation_only else "followup-reconcile"
                        ),
                        "failure-response-available": bool(failure_updates),
                        "dom-signals": sorted(error_evidence),
                    },
                )
                raise RecoveryDeferred(
                    exc,
                    phase="followup-reconcile",
                    side_effect_state="may-have-started",
                    continuation={
                        "kind": "provider-error-observation",
                        "resume-existing": True,
                        "provider-error-followup-attempts": _provider_error_followup_attempts,
                        "default-recovery-attempt": _default_recovery_attempt,
                        "failure-response-available": bool(failure_updates),
                    },
                ) from exc
            if (
                not cancelled
                and runtime_invoked
                and (_network_followup_attempts > 0 or _provider_error_followup_attempts > 0)
            ):
                # A recovery prompt has already been submitted in this
                # provider conversation.  A subsequent provider alert is not
                # proof that the recovery turn did not start: the live tab
                # may still be generating while the old error panel remains
                # in the document.  Preserve the failed-attempt evidence and
                # re-enter observation-only recovery; never terminalize the
                # parent request while that follow-up may still be running.
                failure_updates = _failure_response_updates(project_root, request_id, exc)
                if failure_updates:
                    record = store.update_owned_running_session(
                        project_root,
                        request_id,
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                        session_id=session_id,
                        result_updates=failure_updates,
                    )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "provider.followup.observation-deferred",
                    state="running",
                    attributes={
                        "network-followup-attempts": _network_followup_attempts,
                        "provider-error-followup-attempts": _provider_error_followup_attempts,
                        "same-session": True,
                        "failure-response-available": bool(failure_updates),
                        "dom-signals": sorted(error_evidence),
                    },
                )
                raise RecoveryDeferred(
                    exc,
                    phase="followup-reconcile",
                    side_effect_state="may-have-started",
                    continuation={
                        "kind": "provider-followup",
                        "resume-existing": True,
                        "network-followup-attempts": _network_followup_attempts,
                        "provider-error-followup-attempts": _provider_error_followup_attempts,
                        "default-recovery-attempt": _default_recovery_attempt,
                        "followup-prompt-length": len(dispatch_prompt),
                        "followup-prompt-digest": hashlib.sha256(
                            dispatch_prompt.encode("utf-8")
                        ).hexdigest(),
                    },
                ) from exc
            replacement = None if (load_submission_proven or load_submission_ambiguous) else client_defaults.replace_failed_default(
                project_root, record, exc,
                recover_url=not runtime_invoked and _default_recovery_attempt == 0 and not (record.get("metadata") or {}).get("provider-chat-url"),
                attach_request=not runtime_invoked and _default_recovery_attempt < 2,
            ) if _default_recovery_attempt < 2 or runtime_invoked else None
            if replacement is not None:
                record = replacement
                if not runtime_invoked:
                    return _dispatch_session_request(project_root, record, dispatch_prompt=dispatch_prompt, context_fingerprint=context_fingerprint, _default_recovery_attempt=_default_recovery_attempt + 1)
        exc = _explain_stale_session_runtime_error(project_root, session_id, exc)
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
            updates={
                "error": exc,
                "session-id": session_id,
                "finished-at": now_iso_z(),
                **_failure_response_updates(project_root, request_id, exc),
            },
        )
    except BaseException as exc:
        if guard_held:
            preparation_guard.release()
        if resume_existing and "unresolved turn does not belong to the recovered request" in str(exc):
            current = store.read_record(project_root, request_id)
            cleared = _clear_terminal_predecessor_fence(
                project_root,
                current,
                session_store=session_store,
            )
            if cleared is not None:
                return _dispatch_session_request(
                    project_root,
                    cleared,
                    dispatch_prompt=dispatch_prompt,
                    context_fingerprint=context_fingerprint,
                    _default_recovery_attempt=_default_recovery_attempt,
                    _network_followup_attempts=_network_followup_attempts,
                    _provider_error_followup_attempts=_provider_error_followup_attempts,
                    _unsent_retry_used=_unsent_retry_used,
                    session_start=session_start,
                    project_name=project_name,
                    resume_existing=False,
                )
        if resume_existing:
            cause = repr(exc) or f"<{type(exc).__name__}>"
            wrapped = AudiaGenticError(
                code="INT-AGW-098",
                kind="agents",
                message=f"session recovery failed: {cause}",
                details={"original-type": type(exc).__name__, "original-repr": cause[:500]},
            )
            raise RecoveryDeferred(wrapped) from exc
        # Safety net: wrap any non-AudiaGenticError so _redact_error preserves
        # the message (INT-AGW-098 boundary handler — prevents raw exceptions
        # like provider-specific errors from being silently redacted).
        logger.exception(
            "session dispatch failed with unhandled error",
            extra={"request-id": request_id},
        )
        if request_runtime is not None:
            _quarantine_request_runtime(request_runtime, request_runtime_root.parent / "quarantine")
        cause = repr(exc) or f"<{type(exc).__name__}>"
        wrapped = AudiaGenticError(
            code="INT-AGW-098",
            kind="agents",
            message=f"session dispatch failed: {cause}",
            details={"original-type": type(exc).__name__, "original-repr": cause[:500]},
        )
        if isinstance(exc, Exception) and not resume_existing and _default_recovery_attempt < 2 and not store.read_record(project_root, request_id).get("cancel-requested"):
            replacement = client_defaults.replace_failed_default(
                project_root, record, wrapped,
                recover_url=not runtime_invoked and _default_recovery_attempt == 0 and not (record.get("metadata") or {}).get("provider-chat-url"),
                attach_request=not runtime_invoked,
            )
            if replacement is not None:
                record = replacement
                if not runtime_invoked:
                    return _dispatch_session_request(project_root, record, dispatch_prompt=dispatch_prompt, context_fingerprint=context_fingerprint, _default_recovery_attempt=_default_recovery_attempt + 1)
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
    client_defaults.remember(project_root, record)

    if result.stop_reason == "cancelled":
        # A protocol-level caller cancel is a cancelled request.  A provider
        # can also return ``cancelled`` after a tool execution fails, however;
        # that is a provider-boundary failure, not a clean caller cancel.  The
        # neutral ACP transport records which case occurred so we can retain
        # both the canonical error and any assistant text already produced.
        session_record = session_store.read_session_record(project_root, session_id)
        model_id = session_store.session_model_id(session_record) or record.get("resolved-model-id")
        output_text = _session_output_from_result(result)
        provider_metadata = dict(getattr(result, "metadata", {}) or {})
        cancelled_by_signal = bool(provider_metadata.get("cancelled-by-signal"))
        failed_tool_count = provider_metadata.get("failed-tool-call-count", 0)
        provider_failure = not cancelled_by_signal and not record.get("cancel-requested", False)
        terminal_state = "failed" if provider_failure else "cancelled"
        error: AudiaGenticError | None = None
        if provider_failure:
            failure_code = (
                getattr(result, "error_code", None)
                or ("EXT-ACP-TOOL-001" if failed_tool_count else "EXT-ACP-002")
            )
            error = AudiaGenticError(
                code=failure_code,
                kind="providers",
                message=(
                    "provider returned cancelled without a gateway cancellation"
                    + (" after a tool execution failed" if failed_tool_count else "")
                ),
                details={
                    "stop-reason": result.stop_reason,
                    "reason-code": (
                        "provider-cancelled-after-tool-failure"
                        if failed_tool_count
                        else "provider-cancelled-without-gateway-cancel"
                    ),
                    "failed-tool-call-count": failed_tool_count,
                    "failed-tool-call-ids": provider_metadata.get("failed-tool-call-ids", ()),
                    "assistant-output-available": bool(output_text and output_text.strip()),
                },
            )
        if error is not None and not resume_existing:
            record = client_defaults.replace_failed_default(
                project_root, record, error, recover_url=False, attach_request=False,
            ) or record
        artifact_ref: dict[str, Any] | None = None
        output_preview: str | None = None
        output_truncated = False
        if isinstance(output_text, str) and output_text.strip():
            from audiagentic.components.agents.gateway.output import persist_final_response

            artifact = persist_final_response(project_root, request_id, output_text, media_type=_session_output_media_type(result))
            artifact_ref = {
                key: artifact[key]
                for key in ("artifact-id", "request-id", "media-type", "bytes", "sha256")
            }
            output_preview = artifact["output-preview"]
            output_truncated = artifact["output-truncated"]
        store.append_owned_attempt(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            state=terminal_state,
            error=error,
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
            terminal_state,
            updates={
                "provider-id": provider_id,
                "model-id": model_id,
                "output": output_text,
                "response-artifact": artifact_ref,
                "output-preview": output_preview,
                "output-truncated": output_truncated,
                "error": error,
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
    if not isinstance(output_text, str) or not output_text.strip():
        # A terminal transport acknowledgement is not an agent response.
        # Never stringify a missing summary (which used to persist the literal
        # text ``None`` and report a false completed task).  Keep the durable
        # provider session open so the caller can explicitly retry/reconcile
        # its conversation, but make this request's missing output visible as
        # a provider failure.
        error = AudiaGenticError(
            code="EXT-AGW-119",
            kind="agents",
            message="provider session completed without an assistant response",
            details={"stop-reason": result.stop_reason or "unknown"},
        )
        if not resume_existing:
            record = client_defaults.replace_failed_default(
                project_root, record, error, recover_url=False, attach_request=False,
            ) or record
        store.append_owned_attempt(
            project_root,
            request_id,
            owner_epoch=record["dispatch-owner-epoch"],
            worker_id=record["worker-id"],
            attempt_epoch=record["attempt-epoch"],
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            state="failed",
            error=error,
            started_at=started_at,
            finished_at=now_iso_z(),
        )
        return _transition_owned_attempt(
            project_root,
            record,
            "failed",
            updates={
                "error": error,
                "provider-id": provider_id,
                "model-id": model_id,
                "session-id": session_id,
                "finished-at": now_iso_z(),
            },
        )
    from audiagentic.components.agents.gateway.output import persist_final_response
    artifact = persist_final_response(project_root, request_id, output_text, media_type=_session_output_media_type(result))
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
