"""Agent Execution Gateway live session runtime (plan agent-sessions AS02).

Owns live agent sessions inside the gateway process: one background daemon
thread running an asyncio event loop hosts every provider-neutral transport;
sync gateway code talks to it via run_coroutine_threadsafe. Mirrors the
GatewayQueueManager lifetime pattern (module-level singleton in
agents_gateway_api; sessions die with the host process — the detached
supervisor is AS08).

Process-management guarantees (non-negotiable, see AS02):
- every open transport is registered before first use and closed on exactly
  one of: explicit close, idle timeout, max lifetime, runtime shutdown, or
  interpreter exit (atexit);
- transport.close() is idempotent and bounds child termination, so multiple
  paths racing to close the same session are safe;
- a session whose child died is transitioned 'failed' and removed on the
  next touch or reaper pass — no zombie registry entries.

All registry mutations happen on the session loop thread (coroutines), so
the registry needs no locking. Store I/O from loop coroutines is small
atomic local-file writes; acceptable on the loop (documented tradeoff).

AS28 slice 4a: the OPEN path resolves a provider-neutral transport via the
``providers_api.prepare_provider_session_transport`` seam. No AcpLaunch or
AcpSessionTransport construction in this module's open path.

AS28 slice 4b-A: the prompt, cancel, and close paths now use the neutral
AgentSessionTransport seam (SessionPrompt / ObservationSink / SessionTurnResult /
SessionControlAction.CANCEL_TURN). The ACP callback contract is gone from this
module.
"""

from __future__ import annotations

import asyncio
import atexit
import inspect
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from audiagentic.components.agents.gateway.event_topics import (
    SESSION_CLOSED_TOPIC,
    SESSION_EXPIRED_TOPIC,
    SESSION_FAILED_TOPIC,
    SESSION_OPENED_TOPIC,
    SESSION_ORPHANED_TOPIC,
    SESSION_RESUMED_TOPIC,
    SESSION_TURN_FINISHED_TOPIC,
)
from audiagentic.components.agents.gateway.session import bindings as binding_store
from audiagentic.components.agents.gateway.session import orphan as orphan_lib
from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.components.agents.gateway.session.console_trace import GatewayConsoleTrace
from audiagentic.components.agents.gateway.session.turn_events import (
    _make_on_event_callback,
    _publish_session_event,
)
from audiagentic.components.agents.status.harness_status_evidence import (
    AcceptedEvidence,
    RejectedEvidence,
    StatusEvidenceSink,
)
from audiagentic.components.agents.status.harness_status_observer_ingress import (
    SessionObserverIngress,
)

# AS21 consumer slice: ephemeral evidence projection registry
from audiagentic.components.agents.status.session_lifecycle_projection import (
    SessionEvidenceProjection,
    SessionLifecycleDecision,
)
from audiagentic.components.providers import providers_api
from audiagentic.components.providers.contracts.conversation_focus import ConversationFocusLocator
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    SessionControlAction,
    SessionControlRequest,
    SessionFailureDisposition,
    SessionPrompt,
    SessionTurnResult,
)
from audiagentic.foundation.transports.session_surface import PreparedSessionTransport

logger = logging.getLogger(__name__)


async def _close_failed_transport(transport: Any) -> None:
    """Bound cleanup for a transport whose open transaction did not commit."""
    close = getattr(transport, "close", None)
    if close is None:
        return
    task = asyncio.create_task(close())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except BaseException:  # noqa: BLE001 - cleanup must not mask the open error
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.warning("failed to close transport after unsuccessful open", exc_info=True)


# ── AS28 slice 4a: default provider preparation seam ──────────────
def _default_prepare_fn(
    project_root: Path,
    *,
    provider_id: str,
    ag_session_id: str,
    binding_sink: Any,
    surface_hint: Any,
    model_id: str | None = None,
    model_selector: str | None = None,
    request_runtime_root: Path | None = None,
    mcp_entries=None,
    resume_provider_ref: str | None = None,
    resume_provider_metadata: dict[str, Any] | None = None,
    checkpoint_sink: Any | None = None,
    project_name: str | None = None,
    enable_observability_tap: bool = True,
) -> PreparedSessionTransport:
    """Default provider preparation via the public providers_api seam.

    AS49: ``resume_provider_ref`` forwards to
    ``providers_api.prepare_provider_session_transport`` — when set, the
    resulting transport's ``open()`` resumes that exact provider session
    instead of opening a new one. Callers must have already validated
    resume eligibility (``agents_gateway_session_resume.validate_resume_eligibility``)
    before setting this; this function does not re-check capability.

    ``resume_provider_metadata``: the source session's latest provider-
    metadata (opaque; only gpt-auto's builder currently interprets it, to
    resume the actual conversation rather than the stale open-time ref --
    see session_transport.py's AS49 comments).
    """
    from audiagentic.components.providers import providers_api

    return providers_api.prepare_provider_session_transport(
        project_root,
        provider_id=provider_id,
        ag_session_id=ag_session_id,
        binding_sink=binding_sink,
        surface_hint=surface_hint,
        model_id=model_id,
        model_selector=model_selector,
        request_runtime_root=request_runtime_root,
        mcp_entries=None if mcp_entries is None else tuple(mcp_entries),
        require_isolated_mcp=mcp_entries is not None,
        resume_provider_ref=resume_provider_ref,
        resume_provider_metadata=resume_provider_metadata,
        checkpoint_sink=checkpoint_sink,
        project_name=project_name,
        # Provider-specific enrichment is opt-in at the provider seam.  The
        # public preparation function no-ops for providers without a concrete
        # tap (currently Pi), while Pi needs this enabled to relay ACP/RPC
        # progress before the final response arrives.
        enable_observability_tap=enable_observability_tap,
    )


# Persistent provider conversations are retained until explicitly closed.
# A session may be configured with an inactivity-only cleanup policy by a
# trusted internal composition seam, but a wall-clock maximum lifetime is not
# an execution failure signal and therefore defaults to disabled.
DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS = 0.0
DEFAULT_SESSION_MAX_LIFETIME_SECONDS = 0.0
# A session turn can legitimately pause while a provider runs tools or awaits
# a remote service. Elapsed time is observation policy, not terminal evidence;
# explicit cancellation, provider terminal state, or positively correlated
# owner-death evidence controls the lifecycle.
DEFAULT_TURN_TIMEOUT_SECONDS = 0.0
# In-turn event-silence watchdog: 0 (default) disables. Silence is a configured
# policy timeout for profiles that declare an expected event cadence; it is not
# proof of process death or orphaning.
DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS = 0.0
DEFAULT_REAP_INTERVAL_SECONDS = 30.0
# Max turns waiting on one session's FIFO before new prompts are rejected —
# keeps back-pressure visible instead of building an unbounded backlog (RV513).
DEFAULT_SESSION_QUEUE_MAX = 8
_CLOSE_TIMEOUT_SECONDS = 60.0


def _more_open_bound(current: float, requested: float) -> float:
    """Return the less restrictive of two lifetime bounds.

    ``0`` is the documented opt-out for a bound, so it dominates any
    positive value.  Continuation requests may carry profile/global policy;
    they must not accidentally shorten a conversation that is already live.
    """
    current = float(current)
    requested = float(requested)
    if current == 0 or requested == 0:
        return 0.0
    return max(current, requested)


def _cleanup_preserving(path: Path, preserve: set[Path]) -> None:
    """Delete everything under *path* except entries in *preserve* (and
    whatever directories contain them).

    Used instead of a wholesale rmtree when a provider has durable session
    state living inside its isolated per-request runtime root (see
    PreparedSessionTransport.runtime_preserve_relpaths) -- deleting that
    unconditionally on close, as the old plain rmtree did, silently made
    resume-by-ref impossible regardless of any other resume machinery, since
    there was nothing left on disk to resume from.
    """
    import shutil

    if not path.exists():
        return
    resolved = path.resolve()
    if resolved in preserve:
        return
    if path.is_file() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass
        return
    contains_preserved = any(resolved != p and resolved in p.parents for p in preserve)
    if not contains_preserved:
        shutil.rmtree(path, ignore_errors=True)
        return
    for child in path.iterdir():
        _cleanup_preserving(child, preserve)


class _SessionHandle:
    """Loop-side state for one live session. Touched only on the loop thread."""

    def __init__(
        self,
        *,
        session_id: str,
        transport: Any,
        project_root: Path,
        execution_profile_id: str,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        created_clock: float,
        correlation_id: str | None,
        surface_snapshot: Any = None,
        request_runtime_root: Path | None = None,
        runtime_preserve_relpaths: tuple[str, ...] = (),
    ) -> None:
        self.session_id = session_id
        self.transport = transport
        self.project_root = project_root
        self.execution_profile_id = execution_profile_id
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_lifetime_seconds = max_lifetime_seconds
        self.turn_timeout_seconds = turn_timeout_seconds
        self.turn_silence_timeout_seconds = turn_silence_timeout_seconds
        self.created_clock = created_clock
        self.correlation_id = correlation_id
        # AS28 slice 4a: resolved surface snapshot (provider-neutral metadata)
        self.surface_snapshot = surface_snapshot
        self.request_runtime_root = request_runtime_root
        # Runtime-root-relative paths holding the provider's own durable
        # session state (see PreparedSessionTransport.runtime_preserve_relpaths)
        # -- preserved by _cleanup_handle_runtime instead of being deleted with
        # everything else, so resume-by-ref has something to seed from.
        self.runtime_preserve_relpaths = runtime_preserve_relpaths
        # AS19 Stage-3: observer binding (tied to session lifecycle)
        self.observer_binding_id: str | None = None
        # AS19 Stage-2 Slice A: transport-observation lease from providers_api.
        # Tied to session lifecycle — created on open, used on each turn,
        # invalidated on close/failure.
        self.observer_lease: Any | None = None
        self.last_activity_clock = created_clock
        # In-turn liveness: refreshed by every transport event during a turn
        # (RV680 silence watchdog); meaningful only while a turn is running.
        self.last_event_clock = created_clock
        self.current_request_id: str | None = None
        # AS91: the task remains the sole owner of its finally-based lock and
        # capacity cleanup. The reaper may only cancel this task after positive
        # foundation process-death evidence.
        self.owning_turn_task: asyncio.Task[Any] | None = None
        self.turn_closing_deadline: float | None = None
        self.orphan_cleanup_started = False
        self.failure_started = False
        # Bounded, redacted projection of the most recent turn event this
        # handle has observed (kind/sequence/request-id/timestamp only — no
        # prompt text, tool args, output, or provider refs). Exposed via
        # session_runtime_status() for live diagnostics.
        self.latest_turn_event: dict[str, Any] | None = None
        # AS17/RV681: OS facts for the transport child, captured at open.
        self.child_pid: int | None = None
        self.child_creation_identity: str | None = None
        self.adopted_child: Any | None = None
        # Turns are strictly serialized per session; waiters queue FIFO on the
        # lock (RV513 — queue, don't reject). pending counts waiters only.
        self.turn_lock = asyncio.Lock()
        self.pending = 0

    def quiescent(self) -> bool:
        """True when no turn is running and none are queued."""
        return not self.turn_lock.locked() and self.pending == 0

    def update_bounds(
        self,
        *,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        replace_idle_timeout: bool = False,
    ) -> None:
        """Update lifetime bounds on an existing handle.

        Only mutates the fields that are explicitly provided (not None).
        Called by dispatch when continuing a session with keep-alive and new
        policy values; best-effort — no durable write here, just the in-memory
        handle (the persisted record retains its original values).
        """
        # Continuation policy is a process/global admission setting, not a
        # new identity for the provider conversation.  A narrower request
        # must never shorten an already-live session; the most permissive
        # bound wins (and zero means unbounded).
        if idle_timeout_seconds is not None:
            self.idle_timeout_seconds = idle_timeout_seconds if replace_idle_timeout else _more_open_bound(
                self.idle_timeout_seconds, idle_timeout_seconds
            )
        if max_lifetime_seconds is not None:
            self.max_lifetime_seconds = _more_open_bound(
                self.max_lifetime_seconds, max_lifetime_seconds
            )


class SessionRuntime:
    """Registry + lifecycle owner for live agent sessions.

    One instance per process (module singleton via get_session_runtime()).
    ``clock`` and ``reap_interval_seconds`` are injectable for deterministic
    tests; production uses time.monotonic.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        reap_interval_seconds: float = DEFAULT_REAP_INTERVAL_SECONDS,
        provider_prepare_fn: Any = None,
        session_queue_max: int = DEFAULT_SESSION_QUEUE_MAX,
    ) -> None:
        self._clock = clock
        self._reap_interval = reap_interval_seconds
        self._session_queue_max = session_queue_max
        # Provider preparation seam (AS28 slice 4a): injected for tests;
        # defaults to the real providers_api.prepare_provider_session_transport.
        self._provider_prepare_fn = provider_prepare_fn or _default_prepare_fn
        self._handles: dict[str, _SessionHandle] = {}
        self._console_trace = GatewayConsoleTrace()
        # request-id → cancel event for the turn currently owning that request
        # (loop-thread only). request_cancel() sets these threadsafe (RV680).
        self._turn_cancels: dict[str, asyncio.Event] = {}
        # AS19 Stage-2: observer ingress — manages per-session observer bindings.
        self._observer_ingress = SessionObserverIngress(clock=self._clock)
        # AS21 consumer slice: ephemeral keyed projection registry.
        # Receives accepted AS19 StatusEvidence, feeds project_session_lifecycle,
        # retains latest decision for status read projection only.
        self._evidence_projection = SessionEvidenceProjection()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._shutdown = False

    # ── loop plumbing ────────────────────────────────────────────

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if (
                self._loop is not None
                and self._loop_thread is not None
                and self._loop_thread.is_alive()
            ):
                return self._loop
            if self._shutdown:
                raise AudiaGenticError(
                    code="CON-AGW-002",
                    kind="agents",
                    message="session runtime has been shut down",
                    details={},
                )
            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            thread = threading.Thread(target=_run, daemon=True, name="gateway-session-loop")
            thread.start()
            self._loop = loop
            self._loop_thread = thread

            async def _start_reaper() -> None:
                self._reaper_task = asyncio.get_running_loop().create_task(self._reaper())

            asyncio.run_coroutine_threadsafe(_start_reaper(), loop).result(timeout=10)
            return loop

    def _call(self, coro: Any, timeout: float | None) -> Any:
        """Run *coro* on the runtime loop, cancelling it if *timeout* expires.

        The timeout is applied with ``asyncio.wait_for`` *inside* the loop
        rather than via ``Future.result(timeout=...)``. The latter only stops
        the caller waiting -- the coroutine keeps running to completion on the
        loop.

        That distinction caused real damage (observed 2026-08-09): a session
        open declared TimeoutError at 120.0s went on to finish 11s later and
        registered a live session nobody was waiting for, leaking both the
        session binding and its CDP helper process. The next attempt then
        contended with that orphan on the same provider-ref-key, so failures
        compounded instead of being independent.
        """
        started = time.monotonic()
        logger.info(
            "session runtime call begin timeout=%s timeout-plus-slack=%s",
            timeout,
            None if timeout is None else timeout + 15.0,
            extra={"session-runtime-phase": "call.begin"},
        )
        try:
            loop = self._ensure_loop()
        except BaseException:
            # Public methods construct their coroutine before entering this
            # boundary.  If admission fails synchronously (for example after
            # shutdown), explicitly close it so Python does not report an
            # un-awaited coroutine and no captured resources linger.
            close = getattr(coro, "close", None)
            if close is not None:
                close()
            raise
        if timeout is None:
            result = asyncio.run_coroutine_threadsafe(coro, loop).result()
            logger.info(
                "session runtime call complete elapsed-ms=%.1f timeout=%s",
                (time.monotonic() - started) * 1000,
                timeout,
                extra={"session-runtime-phase": "call.complete"},
            )
            return result

        async def _bounded() -> Any:
            return await asyncio.wait_for(coro, timeout=timeout)

        logger.info(
            "session runtime call submitted inner-wait-for timeout=%.1fs",
            timeout,
            extra={"session-runtime-phase": "call.submitted"},
        )
        future = asyncio.run_coroutine_threadsafe(_bounded(), loop)
        # Allow a little slack over the inner deadline so the inner
        # cancellation is what fires, letting the coroutine unwind its own
        # cleanup rather than being abandoned mid-flight.
        try:
            result = future.result(timeout=timeout + 15.0)
        except Exception:
            logger.exception(
                "session runtime call failed elapsed-ms=%.1f inner-timeout=%.1fs outer-timeout=%.1fs",
                (time.monotonic() - started) * 1000,
                timeout,
                timeout + 15.0,
                extra={"session-runtime-phase": "call.failed"},
            )
            raise
        logger.info(
            "session runtime call complete elapsed-ms=%.1f inner-timeout=%.1fs",
            (time.monotonic() - started) * 1000,
            timeout,
            extra={"session-runtime-phase": "call.complete"},
        )
        return result

    # ── public sync API ──────────────────────────────────────────

    def open_session(
        self,
        project_root: Path,
        *,
        execution_profile_id: str,
        provider_id: str,
        model_id: str | None = None,
        model_selector: str | None = None,
        session_id: str | None = None,
        surface_hint: Any = None,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        turn_timeout_seconds: float | None = None,
        turn_silence_timeout_seconds: float | None = None,
        correlation_id: str | None = None,
        request_runtime_root: Path | None = None,
        mcp_entries=(),
        identity_context_fingerprint: str | None = None,
        execution_context_fingerprint: str | None = None,
        context_id: str | None = None,
        agent_definition_id: str | None = None,
        agent_definition_digest: str | None = None,
        role_ids: tuple[str, ...] | list[str] | None = None,
        role_set_digest: str | None = None,
        execution_profile_digest: str | None = None,
        effective_capability_digest: str | None = None,
        capacity_source_id: str | None = None,
        project_name: str | None = None,
        request_provider_metadata_sink: Any = None,
        resume_provider_ref: str | None = None,
        resume_provider_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a live session; returns the persisted session record.

        AS28 slice 4a: the open path resolves a provider-neutral transport via
        ``providers_api.prepare_provider_session_transport``. The caller supplies
        *provider_id* and *model_id*; no AcpLaunch crosses this boundary.

        When the resolved surface is unsupported or the transport is None,
        raises CON-AGW-095 — no child starts, no live session exposed.
        """
        logger.info(
            "gateway open requested provider=%s model=%s execution-profile=%s activity-governed correlation-id=%s",
            provider_id,
            model_id,
            execution_profile_id,
            correlation_id,
            extra={"session-runtime-phase": "open.request"},
        )
        return self._call(
            self._open_session(
                project_root,
                execution_profile_id=execution_profile_id,
                provider_id=provider_id,
                model_id=model_id,
                model_selector=model_selector,
                session_id=session_id,
                surface_hint=surface_hint,
                # None → gateway default; an explicit 0 DISABLES the bound
                # (needed for long-lived remote-control sessions, RV513).
                idle_timeout_seconds=(
                    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS
                    if idle_timeout_seconds is None
                    else idle_timeout_seconds
                ),
                max_lifetime_seconds=(
                    DEFAULT_SESSION_MAX_LIFETIME_SECONDS
                    if max_lifetime_seconds is None
                    else max_lifetime_seconds
                ),
                turn_timeout_seconds=(
                    DEFAULT_TURN_TIMEOUT_SECONDS
                    if turn_timeout_seconds is None
                    else turn_timeout_seconds
                ),
                turn_silence_timeout_seconds=(
                    DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS
                    if turn_silence_timeout_seconds is None
                    else turn_silence_timeout_seconds
                ),
                correlation_id=correlation_id,
                request_runtime_root=request_runtime_root,
                mcp_entries=tuple(mcp_entries),
                identity_context_fingerprint=identity_context_fingerprint,
                execution_context_fingerprint=execution_context_fingerprint,
                context_id=context_id,
                agent_definition_id=agent_definition_id,
                agent_definition_digest=agent_definition_digest,
                role_ids=role_ids,
                role_set_digest=role_set_digest,
                execution_profile_digest=execution_profile_digest,
                effective_capability_digest=effective_capability_digest,
                capacity_source_id=capacity_source_id,
                project_name=project_name,
                request_provider_metadata_sink=request_provider_metadata_sink,
                resume_provider_ref=resume_provider_ref,
                resume_provider_metadata=resume_provider_metadata,
            ),
            # Opening a provider session is provider work. Do not convert a
            # slow but alive handshake into a terminal request solely because
            # an arbitrary wall clock elapsed.
            timeout=None,
        )

    def prompt_in_session(
        self,
        project_root: Path,
        session_id: str,
        prompt: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        timeout_seconds: float | None = None,
        activity_relay: Any | None = None,
    ) -> SessionTurnResult:
        """Run one turn on a live session; refreshes its idle clock."""
        return self._call(
            self._prompt(
                project_root,
                cast(str, session_id),
                prompt,
                request_id=request_id,
                correlation_id=correlation_id,
                activity_relay=activity_relay,
            ),
            timeout=timeout_seconds,
        )

    def focus_existing_conversation(
        self,
        project_root: Path,
        *,
        provider_id: str,
        locator: ConversationFocusLocator,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        """Focus a provider conversation without creating or navigating tabs."""
        return self._call(
            providers_api.focus_existing_conversation(
                project_root, provider_id=provider_id, locator=locator
            ),
            timeout=timeout_seconds,
        ).to_mapping()

    def resume_session(
        self,
        project_root: Path,
        source_session_id: str,
        *,
        control_id: str,
        execution_context_fingerprint: str | None = None,
        context_id: str | None = None,
        agent_definition_id: str | None = None,
        agent_definition_digest: str | None = None,
        role_ids: tuple[str, ...] | list[str] | None = None,
        role_set_digest: str | None = None,
        execution_profile_digest: str | None = None,
        effective_capability_digest: str | None = None,
        model_id: str | None = None,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        turn_timeout_seconds: float | None = None,
        turn_silence_timeout_seconds: float | None = None,
        correlation_id: str | None = None,
        request_runtime_root: Path | None = None,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        """AS49: explicitly resume a terminal session as a new linked generation.

        Never triggered by ordinary continuation — only an explicit client
        request naming the exact terminal ``source_session_id``. ``control_id``
        makes the request idempotent: a repeated call with the same id returns
        the original result rather than creating a second successor.

        ``execution_context_fingerprint`` is an internally derived current
        SH02 context used only when the resolved provider surface declares
        that resume requires the same execution context. Persistent provider
        conversations opt out through their surface mapping facts.
        """
        return self._call(
            self._resume_session(
                project_root,
                source_session_id,
                control_id=control_id,
                execution_context_fingerprint=execution_context_fingerprint,
                context_id=context_id,
                agent_definition_id=agent_definition_id,
                agent_definition_digest=agent_definition_digest,
                role_ids=role_ids,
                role_set_digest=role_set_digest,
                execution_profile_digest=execution_profile_digest,
                effective_capability_digest=effective_capability_digest,
                model_id=model_id,
                idle_timeout_seconds=(
                    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS
                    if idle_timeout_seconds is None
                    else idle_timeout_seconds
                ),
                max_lifetime_seconds=(
                    DEFAULT_SESSION_MAX_LIFETIME_SECONDS
                    if max_lifetime_seconds is None
                    else max_lifetime_seconds
                ),
                turn_timeout_seconds=(
                    DEFAULT_TURN_TIMEOUT_SECONDS
                    if turn_timeout_seconds is None
                    else turn_timeout_seconds
                ),
                turn_silence_timeout_seconds=(
                    DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS
                    if turn_silence_timeout_seconds is None
                    else turn_silence_timeout_seconds
                ),
                correlation_id=correlation_id,
                request_runtime_root=request_runtime_root,
                project_name=project_name,
            ),
            timeout=None,
        )

    def close_session(
        self,
        project_root: Path,
        session_id: str,
        *,
        reason: str = "client-request",
    ) -> dict[str, Any]:
        """Close a live session (idempotent); returns the final record."""
        return self._call(
            self._close(project_root, session_id, reason=reason),
            timeout=_CLOSE_TIMEOUT_SECONDS,
        )

    def live_session_ids(self) -> list[str]:
        """Session ids with a live handle in this process."""
        if self._loop is None:
            return []
        return self._call(self._snapshot_ids(), timeout=10)

    def session_snapshot_all(self) -> dict[str, dict[str, Any]]:
        """Immutable snapshot of all live sessions' state at one instant.

        Returns {session-id: {turn-active, pending-turns, current-request-id}}
        for every handle alive at read time. Empty when the loop is not started.
        """
        if self._loop is None:
            return {}
        return self._call(self._session_snapshot_all(), timeout=10)

    def session_runtime_status(self, session_id: str) -> dict[str, Any]:
        """Read-only, redacted live facts for one session in this process."""
        if self._loop is None:
            return {"available": False}
        return self._call(self._session_runtime_status(session_id), timeout=10)

    def reconcile_active_transport(self, session_id: str, request_id: str) -> dict[str, Any]:
        """Ask a live transport to revalidate an active turn's binding.

        This is a narrow recovery seam for watchdog transport-stale evidence.
        It never submits a prompt, creates a session, or changes lifecycle
        state; providers may only reattach/reconcile their existing turn.
        """
        if self._loop is None:
            return {"status": "unavailable", "reason": "session-runtime-inactive"}
        return self._call(
            self._reconcile_active_transport(session_id, request_id), timeout=10
        )

    def latest_lifecycle_decision(
        self, session_id: str, request_id: str
    ) -> SessionLifecycleDecision | None:
        """Read the latest AS21 decision without starting or mutating the runtime."""
        return self._evidence_projection.latest_decision_for_key(session_id, request_id)

    def update_session_bounds(
        self,
        session_id: str,
        *,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        replace_idle_timeout: bool = False,
    ) -> None:
        """Update lifetime bounds on a live session handle.

        Used when continuing an existing session with keep-alive and new
        policy values. Only mutates the in-memory handle; the persisted
        session record retains its original values (bounds are fixed at
        open time for durable records).

        Raises RES-AGW-003 if the session is not live in this process.
        """
        if self._loop is None:
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="session is not active in this gateway process",
                details={"session-id": session_id},
            )

        async def _update() -> None:
            handle = self._require_handle(session_id)
            handle.update_bounds(
                idle_timeout_seconds=idle_timeout_seconds,
                max_lifetime_seconds=max_lifetime_seconds,
                replace_idle_timeout=replace_idle_timeout,
            )

        self._call(_update(), timeout=10)

    def rehydrate_session(
        self,
        project_root: Path,
        session_id: str,
        *,
        execution_profile_id: str,
        provider_id: str,
        model_id: str | None,
        surface_hint: Any,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        turn_timeout_seconds: float | None = None,
        turn_silence_timeout_seconds: float | None = None,
        correlation_id: str | None = None,
        request_runtime_root: Path | None = None,
        mcp_entries=(),
        project_name: str | None = None,
    ) -> dict[str, Any]:
        """Reattach an active durable generation after a runtime restart.

        A gateway process owns only ephemeral transport handles.  The durable
        session record, however, remains ``active`` across a process restart.
        Continuation therefore reopens the exact provider binding in-place;
        it is not a new chat and it does not create a successor generation.
        The provider ref is mandatory and is checked both before and after
        ``open()`` so a provider can never silently substitute a conversation.
        """
        return self._call(
            self._rehydrate_session(
                project_root,
                session_id,
                execution_profile_id=execution_profile_id,
                provider_id=provider_id,
                model_id=model_id,
                surface_hint=surface_hint,
                idle_timeout_seconds=(
                    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS
                    if idle_timeout_seconds is None
                    else idle_timeout_seconds
                ),
                max_lifetime_seconds=(
                    DEFAULT_SESSION_MAX_LIFETIME_SECONDS
                    if max_lifetime_seconds is None
                    else max_lifetime_seconds
                ),
                turn_timeout_seconds=(
                    DEFAULT_TURN_TIMEOUT_SECONDS
                    if turn_timeout_seconds is None
                    else turn_timeout_seconds
                ),
                turn_silence_timeout_seconds=(
                    DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS
                    if turn_silence_timeout_seconds is None
                    else turn_silence_timeout_seconds
                ),
                correlation_id=correlation_id,
                request_runtime_root=request_runtime_root,
                mcp_entries=tuple(mcp_entries),
                project_name=project_name,
            ),
            timeout=None,
        )

    def session_is_quiescent(self, session_id: str) -> bool:
        """Check if a live session has no active or pending turns.

        Used by dispatch to decide post-turn close policy for continued
        sessions with keep-alive=false.
        """
        if self._loop is None:
            return True  # not live → treat as quiescent for close purposes

        async def _check() -> bool:
            handle = self._handles.get(session_id)
            return handle.quiescent() if handle else True

        return self._call(_check(), timeout=10)

    def request_cancel(self, request_id: str, *, session_id: str | None = None) -> bool:
        """Signal protocol-level cancel to the turn owning *request_id*.

        AS28 slice 4b-A: issues SessionControlAction.CANCEL_TURN via the
        neutral transport.control() seam when *session_id* is provided. When
        only *request_id* is given, falls back to the local cancel event map
        (retained for callers that cannot resolve the session id; this is a
        migration path). Returns True when the signal was scheduled; False
        otherwise. Best-effort and threadsafe (RV680): the turn observes it
        via the transport's internal cancel race and finishes with
        stop_reason 'cancelled'. A request not currently in a turn is a no-op.
        """
        with self._loop_lock:
            loop = self._loop
        if loop is None or not loop.is_running():
            return False

        if session_id is not None:
            # AS28 slice 4b-A: neutral control path.
            async def _cancel() -> bool:
                handle = self._handles.get(session_id)
                if handle is None or not handle.transport.is_alive():
                    return False
                control_req = SessionControlRequest(
                    ag_session_id=session_id,
                    turn_id=request_id,
                    action=SessionControlAction.CANCEL_TURN,
                )
                result = await handle.transport.control(control_req)
                return bool(
                    getattr(result, "disposition", None)
                    in (
                        "accepted",
                        "already-terminal",
                    )
                )

            try:
                return self._call(_cancel(), timeout=5.0)
            except Exception:  # noqa: BLE001 — cancel must never raise
                logger.warning(
                    "cancel control request failed",
                    extra={"session-id": session_id, "request-id": request_id},
                    exc_info=True,
                )
                return False

        # Fallback: local cancel event map (migration path for callers that
        # cannot resolve session_id from the request record). This sets the
        # per-request asyncio.Event so the transport's internal cancel race
        # sees it. The _turn_cancels dict is populated in _prompt().
        def _set_local() -> None:
            event = self._turn_cancels.get(request_id)
            if event is not None:
                event.set()

        loop.call_soon_threadsafe(_set_local)
        return True

    def control_session(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        action: SessionControlAction,
        control_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch one closed, provider-neutral live-session control.

        This is deliberately acknowledgement-only: it invokes the frozen
        transport control seam but does not transition request/session state,
        release capacity, or manufacture an outcome.  Those remain owned by
        the normal evidence and terminal-transition paths.
        """
        if self._loop is None:
            return {"disposition": "uncertain", "error-code": "RES-AGW-003"}

        async def _control() -> dict[str, Any]:
            handle = self._handles.get(session_id)
            if handle is None:
                return {"disposition": "already-terminal"}
            if action is SessionControlAction.CLOSE_SESSION:
                # Session closure is a gateway lifecycle transition. Do not
                # let a provider close its transport underneath an active
                # durable handle; close only after the serialized turn queue
                # is quiescent.
                if not handle.quiescent():
                    return {"disposition": "rejected", "error-code": "CON-AGW-004"}
                await self._close(handle.project_root, session_id, reason="client-request")
                return {
                    "disposition": "accepted",
                    "correlation-quality": "request-scoped",
                    "error-code": None,
                }
            request = SessionControlRequest(
                ag_session_id=session_id,
                turn_id=turn_id,
                action=action,
                request_id=control_id,
                payload=payload or {},
            )
            result = await handle.transport.control(request)
            return {
                "disposition": result.disposition.value,
                "correlation-quality": result.correlation_quality.value,
                "error-code": result.error_code,
            }

        return self._call(_control(), timeout=10)

    # ── AS19 Stage-2: observer binding management ────────────────

    def create_observer_binding(
        self,
        session_id: str,
        project_root: str,
    ) -> tuple[str, str, str]:
        """Create an observer binding for a session.

        Returns (binding_id, token, ingress_endpoint). The token is used to
        validate incoming observation requests from hooks/plugins.

        Binding lifecycle is tied to session lifecycle — the binding is
        automatically invalidated when the session closes or fails.

        Raises:
            AudiaGenticError: if the session already has an active observer
                binding (one binding per session).
        """
        return self._observer_ingress.create_observer_binding(
            session_id=session_id,
            project_root=project_root,
        )

    def invalidate_binding(self, binding_id: str) -> None:
        """Invalidate an observer binding.

        Called directly or indirectly via session close/failure. Idempotent.
        """
        self._observer_ingress.invalidate_binding(binding_id)

    def shutdown(
        self,
        *,
        before_loop_stop: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Close every live session and stop accepting new ones. Idempotent."""
        with self._loop_lock:
            self._shutdown = True
            loop = self._loop
        if loop is None:
            return
        try:

            async def _shutdown_loop() -> None:
                await self._close_all(reason="shutdown")
                if self._reaper_task is not None and not self._reaper_task.done():
                    self._reaper_task.cancel()
                    await asyncio.gather(self._reaper_task, return_exceptions=True)
                if before_loop_stop is not None:
                    # Provider transports and their CDP sockets are bound to
                    # this loop. Finalize them after sessions are drained but
                    # before the owning event loop is stopped.
                    await before_loop_stop()

            asyncio.run_coroutine_threadsafe(_shutdown_loop(), loop).result(
                timeout=_CLOSE_TIMEOUT_SECONDS
            )
        except Exception:  # noqa: BLE001 — continue loop teardown after close failures
            logger.warning("session runtime shutdown incomplete", exc_info=True)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread = self._loop_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=_CLOSE_TIMEOUT_SECONDS)
            if not loop.is_running() and not loop.is_closed():
                loop.close()
            with self._loop_lock:
                self._loop = None
                self._loop_thread = None
                self._reaper_task = None

    # ── loop-side implementation ─────────────────────────────────

    async def _snapshot_ids(self) -> list[str]:
        return list(self._handles)

    async def _session_snapshot_all(self) -> dict[str, dict[str, Any]]:
        """Immutable snapshot of every live session's state at one instant.

        Reads all handles on the loop thread (no additional locking needed —
        _handles is only mutated on this thread). The returned dict maps
        session-id → {turn-active, pending-turns, current-request-id} for
        each handle present at read time.
        """
        return {
            sid: {
                "turn-active": h.turn_lock.locked(),
                "pending-turns": h.pending,
                "current-request-id": h.current_request_id,
            }
            for sid, h in self._handles.items()
        }

    async def _session_runtime_status(self, session_id: str) -> dict[str, Any]:
        handle = self._handles.get(session_id)
        if handle is None:
            return {"available": False}
        # AS21 consumer slice: surface redacted lifecycle-decision from
        # the evidence projection registry (no raw evidence, no provider refs).
        current_request = handle.current_request_id
        status_snapshot = self._evidence_projection.redacted_status_snapshot(
            session_id,
            request_id=current_request,
        )
        return {
            "available": True,
            "pending-turns": handle.pending,
            "turn-active": handle.turn_lock.locked(),
            "current-request-id": handle.current_request_id,
            "child-pid": handle.child_pid,
            "latest-turn-event": handle.latest_turn_event,
            "lifecycle-decision": status_snapshot["lifecycle-decision"],
            "coarse-state": status_snapshot["coarse-state"],
        }

    async def _reconcile_active_transport(
        self, session_id: str, request_id: str
    ) -> dict[str, Any]:
        handle = self._handles.get(session_id)
        if handle is None:
            return {"status": "unavailable", "reason": "session-not-live"}
        if handle.current_request_id != request_id:
            return {"status": "not-owner", "reason": "request-is-not-active-turn"}
        reconcile = getattr(handle.transport, "reconcile_activity_gap", None)
        if not callable(reconcile):
            return {"status": "unsupported", "reason": "transport-no-reconcile-seam"}
        try:
            result = await reconcile()
        except Exception as exc:  # noqa: BLE001 - diagnostic recovery is advisory
            logger.warning(
                "active transport reconciliation failed",
                extra={"session-id": session_id, "request-id": request_id},
                exc_info=True,
            )
            return {"status": "failed", "reason": type(exc).__name__}
        return result if isinstance(result, dict) else {"status": "reconciled"}

    async def _rehydrate_session(
        self,
        project_root: Path,
        session_id: str,
        *,
        execution_profile_id: str,
        provider_id: str,
        model_id: str | None,
        surface_hint: Any,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        correlation_id: str | None,
        request_runtime_root: Path | None,
        mcp_entries,
        project_name: str | None,
    ) -> dict[str, Any]:
        # The loop serializes this check with every other session operation;
        # concurrent continuations cannot open two browser/provider handles.
        if session_id in self._handles:
            handle = self._handles[session_id]
            handle.update_bounds(
                idle_timeout_seconds=idle_timeout_seconds,
                max_lifetime_seconds=max_lifetime_seconds,
            )
            return session_store.read_session_record(project_root, session_id)

        record = session_store.read_session_record(project_root, session_id)
        if record.get("state") != "active":
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="session is not active and cannot be rehydrated",
                details={"session-id": session_id, "state": record.get("state")},
            )
        if record.get("execution-profile-id") != execution_profile_id:
            raise AudiaGenticError(
                code="VAL-AGW-060",
                kind="agents",
                message="request execution profile does not match the session's profile",
                details={"session-id": session_id},
            )
        binding = session_store.read_session_binding(project_root, session_id)
        provider_ref = (binding or {}).get("provider-session-ref")
        bound_provider = (binding or {}).get("provider-id") or session_store.session_provider_id(record)
        surface_id = (binding or {}).get("surface-id")
        if not isinstance(provider_ref, str) or not provider_ref.strip():
            metadata = session_store.session_provider_metadata(record)
            # Gated on a provider capability probe (does bound_provider's
            # adapter declare a non-ACP session transport, e.g. gpt-auto's
            # CDP seam) rather than a surface_id or provider_id literal --
            # applies to any provider with this shape, including the
            # dedicated gpt-auto-t1/t2 test projects, with no code change
            # needed when a new one is added.
            from audiagentic.components.providers import providers_api

            if metadata.get(
                "unresolved-turn-pending"
            ) and providers_api.provider_declares_session_transport(bound_provider or ""):
                raise AudiaGenticError(
                    code="RES-AGW-003",
                    kind="agents",
                    message=(
                        "active gpt-auto session has an unresolved turn but no durable "
                        "provider conversation binding; the first Send may have reached "
                        "ChatGPT before the gateway lost identity"
                    ),
                    details={
                        "session-id": session_id,
                        "recovery-state": metadata.get("recovery-state"),
                        "turn-id": metadata.get("unresolved-turn-id"),
                        "suggestion": (
                            "inspect the retained ChatGPT tab for the submitted prompt; "
                            "resume only after its outcome is proven, otherwise resubmit"
                        ),
                    },
                )
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="active session has no durable provider binding to rehydrate",
                details={"session-id": session_id, "suggestion": "resume the session explicitly"},
            )
        if bound_provider and bound_provider != provider_id:
            raise AudiaGenticError(
                code="CON-AGW-120",
                kind="agents",
                message="durable provider binding does not match the requested provider",
                details={"session-id": session_id, "provider-id": provider_id},
            )
        if not isinstance(surface_id, str) or not surface_id.strip():
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="active session has no durable surface binding to rehydrate",
                details={"session-id": session_id, "suggestion": "resume the session explicitly"},
            )

        async def binding_sink(update: Any) -> None:
            update_ref = getattr(getattr(update, "provider_session_ref", None), "value", None)
            if update_ref != provider_ref:
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="rehydrated provider attempted to replace its session binding",
                    details={"session-id": session_id},
                )
            session_store.install_initial_provider_binding(
                project_root,
                session_id,
                provider_id=provider_id,
                surface_id=surface_id,
                provider_session_ref=provider_ref,
                metadata=dict(getattr(update, "metadata", {}) or {}),
            )

        async def checkpoint_sink(metadata: dict[str, Any]) -> None:
            pending = bool(metadata.get("unresolved-turn-pending"))
            remove = () if pending else (
                "recovery-state",
                "unresolved-turn-id",
                "unresolved-baseline-user-id",
                "unresolved-baseline-assistant-id",
                "unresolved-baseline-user-count",
                "unresolved-baseline-assistant-count",
            )
            session_store.update_provider_metadata(
                project_root, session_id, metadata, remove_keys=remove
            )

        prepare_kwargs: dict[str, Any] = {
            "provider_id": provider_id,
            "ag_session_id": session_id,
            "binding_sink": binding_sink,
            "surface_hint": surface_hint,
            "model_id": model_id or session_store.session_model_id(record),
            "resume_provider_ref": provider_ref,
            "resume_provider_metadata": session_store.session_provider_metadata(record),
            "checkpoint_sink": checkpoint_sink,
            "project_name": project_name,
        }
        if request_runtime_root is not None:
            prepare_kwargs["request_runtime_root"] = request_runtime_root
            prepare_kwargs["mcp_entries"] = tuple(mcp_entries)
        transport = None
        try:
            prepared = self._provider_prepare_fn(project_root, **prepare_kwargs)
            if prepared.transport is None:
                raise AudiaGenticError(
                    code="CON-AGW-095",
                    kind="agents",
                    message="resolved session surface is unsupported; cannot rehydrate session",
                    details={"session-id": session_id, "provider-id": provider_id},
                )
            transport = prepared.transport
            open_result = await transport.open()
        except asyncio.CancelledError:
            if transport is not None:
                await _close_failed_transport(transport)
            raise
        except AudiaGenticError:
            if transport is not None:
                await _close_failed_transport(transport)
            raise
        except Exception as exc:  # noqa: BLE001 - preserve provider cause
            if transport is not None:
                await _close_failed_transport(transport)
            raise AudiaGenticError(
                code="EXT-AGW-118",
                kind="agents",
                message="provider rejected durable session rehydration",
                details={
                    "session-id": session_id,
                    "provider-id": provider_id,
                    "error-type": type(exc).__name__,
                    "error-message": str(exc).strip(),
                },
            ) from exc

        try:
            returned_ref = getattr(getattr(open_result, "provider_session_ref", None), "value", None)
            if open_result.ag_session_id != session_id or returned_ref != provider_ref:
                raise AudiaGenticError(
                    code="CON-AGW-121",
                    kind="agents",
                    message="rehydrated transport did not prove the original session identity",
                    details={"session-id": session_id},
                )
        except BaseException:
            await _close_failed_transport(transport)
            raise

        handle = _SessionHandle(
            session_id=session_id,
            transport=transport,
            project_root=project_root,
            execution_profile_id=execution_profile_id,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            turn_timeout_seconds=turn_timeout_seconds,
            turn_silence_timeout_seconds=turn_silence_timeout_seconds,
            created_clock=self._clock(),
            correlation_id=correlation_id,
            surface_snapshot=getattr(prepared, "surface", None),
            request_runtime_root=request_runtime_root,
            runtime_preserve_relpaths=getattr(prepared, "runtime_preserve_relpaths", ()),
        )
        handle.child_pid = getattr(transport, "child_pid", None)
        handle.adopted_child = getattr(transport, "_adopted_child", None)
        self._trace_session_opened(
            handle,
            provider_id=provider_id,
            model_id=model_id or session_store.session_model_id(record),
        )
        # Rehydration happens in a fresh gateway process, so recreate the
        # process-local observer binding before exposing the handle. Observer
        # failure remains best-effort, matching the normal open path.
        try:
            binding_id, _token, _endpoint = self._observer_ingress.create_observer_binding(
                session_id=session_id,
                project_root=str(project_root),
            )
            handle.observer_binding_id = binding_id
        except AudiaGenticError:
            logger.warning(
                "failed to create observer binding on session rehydration",
                extra={"session-id": session_id},
                exc_info=True,
            )
        self._handles[session_id] = handle
        session_store.record_session_timeline(
            project_root,
            session_id,
            "session.rehydrated",
            state="active",
            attributes={"provider-id": provider_id, "correlation-id": correlation_id},
        )
        return session_store.read_session_record(project_root, session_id)

    async def _open_session(
        self,
        project_root: Path,
        *,
        execution_profile_id: str,
        provider_id: str,
        model_id: str | None,
        session_id: str | None,
        surface_hint: Any,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        correlation_id: str | None,
        request_runtime_root: Path | None,
        mcp_entries,
        model_selector: str | None = None,
        identity_context_fingerprint: str | None = None,
        execution_context_fingerprint: str | None = None,
        context_id: str | None = None,
        agent_definition_id: str | None = None,
        agent_definition_digest: str | None = None,
        role_ids: tuple[str, ...] | list[str] | None = None,
        role_set_digest: str | None = None,
        execution_profile_digest: str | None = None,
        effective_capability_digest: str | None = None,
        capacity_source_id: str | None = None,
        project_name: str | None = None,
        request_provider_metadata_sink: Any = None,
        resume_provider_ref: str | None = None,
        resume_provider_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        logger.info(
            "gateway open coroutine begin provider=%s model=%s profile=%s",
            provider_id,
            model_id,
            execution_profile_id,
            extra={"session-runtime-phase": "open.begin", "correlation-id": correlation_id},
        )
        if self._shutdown:
            raise AudiaGenticError(
                code="CON-AGW-002",
                kind="agents",
                message="session runtime has been shut down",
                details={},
            )
        session_id = session_id or session_store.generate_session_id()
        allocated_session_id = session_id

        async def binding_sink(update: Any) -> None:
            metadata = dict(update.metadata)
            session_store.install_initial_provider_binding(
                project_root,
                allocated_session_id,
                provider_id=provider_id,
                surface_id=surface_hint.surface_id,
                provider_session_ref=update.provider_session_ref.value,
                metadata=metadata,
                identity_context_fingerprint=identity_context_fingerprint,
                execution_context_fingerprint=execution_context_fingerprint,
                context_id=context_id,
                agent_definition_id=agent_definition_id,
                agent_definition_digest=agent_definition_digest,
                role_ids=role_ids,
                role_set_digest=role_set_digest,
                execution_profile_digest=execution_profile_digest,
                effective_capability_digest=effective_capability_digest,
            )
            # Provider identity is discovered during the first turn, after
            # the request has entered ``running``.  Relay that immutable
            # binding metadata (especially GPT's durable chat URL) to the
            # request immediately so operator surfaces can locate an active
            # tab; terminal dispatch will still persist the final snapshot.
            if request_provider_metadata_sink is not None:
                try:
                    relay_result = request_provider_metadata_sink(metadata)
                    if inspect.isawaitable(relay_result):
                        await relay_result
                except Exception:  # noqa: BLE001 - dashboard metadata is best-effort
                    logger.warning(
                        "failed to relay provider identity to running request",
                        extra={"session-id": allocated_session_id},
                        exc_info=True,
                    )

        async def checkpoint_sink(metadata: dict[str, Any]) -> None:
            pending = bool(metadata.get("unresolved-turn-pending"))
            remove = () if pending else (
                "recovery-state",
                "unresolved-turn-id",
                "unresolved-baseline-user-id",
                "unresolved-baseline-assistant-id",
                "unresolved-baseline-user-count",
                "unresolved-baseline-assistant-count",
            )
            session_store.update_provider_metadata(
                project_root,
                allocated_session_id,
                metadata,
                remove_keys=remove,
            )

        # AS28 slice 4a: resolve provider-neutral transport via the public
        # prepare seam. No AcpLaunch / AcpSessionTransport construction here.
        prepare_kwargs = {
            "provider_id": provider_id,
            "ag_session_id": session_id,
            "binding_sink": binding_sink,
            "surface_hint": surface_hint,
            "model_id": model_id,
            "model_selector": model_selector,
            "checkpoint_sink": checkpoint_sink,
            "project_name": project_name,
        }
        if resume_provider_ref is not None:
            prepare_kwargs["resume_provider_ref"] = resume_provider_ref
        if resume_provider_metadata is not None:
            prepare_kwargs["resume_provider_metadata"] = resume_provider_metadata
        if request_runtime_root is not None:
            prepare_kwargs["request_runtime_root"] = request_runtime_root
            prepare_kwargs["mcp_entries"] = tuple(mcp_entries)
        prepare_started = time.monotonic()
        logger.info(
            "gateway open phase prepare-provider begin provider=%s model=%s",
            provider_id,
            model_id,
            extra={"session-runtime-phase": "open.prepare.begin", "correlation-id": correlation_id},
        )
        prepared = self._provider_prepare_fn(project_root, **prepare_kwargs)
        logger.info(
            "gateway open phase prepare-provider complete elapsed-ms=%.1f transport=%s",
            (time.monotonic() - prepare_started) * 1000,
            type(prepared.transport).__name__ if prepared.transport is not None else None,
            extra={
                "session-runtime-phase": "open.prepare.complete",
                "correlation-id": correlation_id,
            },
        )
        if prepared.transport is None:
            raise AudiaGenticError(
                code="CON-AGW-095",
                kind="agents",
                message="resolved session surface is unsupported; cannot open session",
                details={
                    "provider-id": provider_id,
                    "surface-validation-state": getattr(
                        getattr(prepared, "surface", None), "validation", None
                    )
                    and getattr(prepared.surface.validation, "state", "unknown"),
                },
            )
        transport = prepared.transport
        transport_started = time.monotonic()
        logger.info(
            "gateway open phase transport-open begin transport=%s",
            type(transport).__name__,
            extra={
                "session-runtime-phase": "open.transport.begin",
                "correlation-id": correlation_id,
            },
        )
        try:
            open_result = await transport.open()
        except BaseException:
            logger.exception(
                "gateway open phase transport-open failed elapsed-ms=%.1f",
                (time.monotonic() - transport_started) * 1000,
                extra={
                    "session-runtime-phase": "open.transport.failed",
                    "correlation-id": correlation_id,
                },
            )
            await _close_failed_transport(transport)
            raise
        logger.info(
            "gateway open phase transport-open complete elapsed-ms=%.1f provider-ref-present=%s",
            (time.monotonic() - transport_started) * 1000,
            bool(getattr(open_result, "provider_session_ref", None)),
            extra={
                "session-runtime-phase": "open.transport.complete",
                "correlation-id": correlation_id,
            },
        )
        if open_result.ag_session_id != session_id:
            await _close_failed_transport(transport)
            raise AudiaGenticError(
                code="CON-AGW-121",
                kind="agents",
                message="provider transport returned a different gateway session id",
                details={"session-id": session_id, "provider-id": provider_id},
            )
        provider_session_ref = (
            open_result.provider_session_ref.value
            if open_result.provider_session_ref is not None
            else None
        )
        provider_metadata = dict(getattr(open_result, "metadata", {}) or {})
        if capacity_source_id:
            # This is session-specific placement identity, not a shared
            # profile setting. Continuations must reacquire the same physical
            # source as the transport they reuse.
            provider_metadata["gateway-capacity-source-id"] = capacity_source_id

        # Admission creates the durable gateway session before queueing.  The
        # provider open phase may fill its binding, but must retain the
        # request-owned identity and original creation time rather than
        # replacing that record with an unrelated session.
        try:
            admitted_record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError as exc:
            if exc.code != "RES-AGW-002":
                raise
            # Direct SessionRuntime users are an explicit low-level test and
            # management seam. Gateway request admission always creates this
            # record first; retain this narrow fallback so runtime ownership
            # itself does not manufacture a different record shape.
            admitted_record = session_store.build_session_record(
                session_id=session_id,
                provider_transport_kind="provider-session",
                execution_profile_id=execution_profile_id,
                provider_id=provider_id,
                model_id=model_id,
                idle_timeout_seconds=idle_timeout_seconds,
                max_lifetime_seconds=max_lifetime_seconds,
            )
            session_store.write_session_record(project_root, admitted_record)
        if admitted_record.get("provider-transport-kind") != "provider-session":
            await _close_failed_transport(transport)
            raise AudiaGenticError(
                code="CON-AGW-122",
                kind="agents",
                message="worker-backed gateway session cannot open a provider transport",
                details={"session-id": session_id},
            )
        record = session_store.build_session_record(
            session_id=session_id,
            created_by_request_id=admitted_record.get("created-by-request-id"),
            provider_transport_kind="provider-session",
            execution_profile_id=execution_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            provider_session_ref=provider_session_ref,
            surface_id=prepared.surface.ref.surface_id,
            provider_metadata=provider_metadata,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            identity_context_fingerprint=identity_context_fingerprint,
            execution_context_fingerprint=execution_context_fingerprint,
            created_at=(admitted_record.get("timing") or {}).get("created-at"),
        )
        session_id = str(record["session-id"])
        try:
            bookkeeping_started = time.monotonic()
            logger.info(
                "gateway open phase bookkeeping begin session-id=%s",
                session_id,
                extra={
                    "session-runtime-phase": "open.bookkeeping.begin",
                    "correlation-id": correlation_id,
                },
            )
            session_store.write_session_record(project_root, record)
            binding_store.register_open_binding(project_root, record)
            logger.info(
                "gateway open phase bookkeeping complete elapsed-ms=%.1f session-id=%s",
                (time.monotonic() - bookkeeping_started) * 1000,
                session_id,
                extra={
                    "session-runtime-phase": "open.bookkeeping.complete",
                    "correlation-id": correlation_id,
                },
            )
        except BaseException:
            # Never leak a child because bookkeeping failed.
            await _close_failed_transport(transport)
            raise
        # AS17/RV681: capture OS process facts for the child at open time so
        # diagnostics and reaping have real evidence, not just a transport flag.
        # The transport's _adopted_child holds the AdoptedChild token with
        # ProcessEvidence; we project its facts into session events.
        child_pid = getattr(transport, "child_pid", None)
        child_creation_identity: str | None = None
        child_evidence_available: bool = False
        if child_pid is not None:
            try:
                from audiagentic.foundation.system.managed_process import (
                    process_creation_identity,
                )

                child_creation_identity = process_creation_identity(child_pid)
            except Exception:  # noqa: BLE001 — evidence is best-effort
                logger.debug("failed to capture child creation identity", exc_info=True)
            # Check if foundation adopted the child (AS17 contract).
            try:
                from audiagentic.foundation.system.adopted_process import AdoptedChild

                adopted_token = getattr(transport, "_adopted_child", None)
                child_evidence_available = (
                    isinstance(adopted_token, AdoptedChild) and adopted_token.evidence is not None
                )
            except Exception:  # noqa: BLE001 — evidence check is best-effort
                pass
        try:
            session_store.record_session_timeline(
                project_root,
                session_id,
                "session.opened",
                state="active",
                attributes={
                    "execution-profile-id": execution_profile_id,
                    "provider-id": provider_id,
                    "model-id": model_id,
                    "idle-timeout-seconds": idle_timeout_seconds,
                    "max-lifetime-seconds": max_lifetime_seconds,
                    "turn-timeout-seconds": turn_timeout_seconds,
                    "child-pid": child_pid,
                    # AS17: project foundation process facts — not just pid,
                    # but ownership evidence that proves identity.
                    "child-creation-identity": child_creation_identity,
                    "foundation-evidence-available": child_evidence_available,
                    "binding": binding_store.public_binding_projection(record.get("binding")),
                    "correlation-id": correlation_id,
                },
            )
        except Exception:  # noqa: BLE001 — a timeline failure must not leak
            # the child (the handle below is what guarantees eventual cleanup).
            logger.warning(
                "failed to record session.opened timeline",
                extra={"session-id": session_id},
                exc_info=True,
            )
        handle = _SessionHandle(
            session_id=session_id,
            transport=transport,
            project_root=project_root,
            execution_profile_id=execution_profile_id,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            turn_timeout_seconds=turn_timeout_seconds,
            turn_silence_timeout_seconds=turn_silence_timeout_seconds,
            created_clock=self._clock(),
            correlation_id=correlation_id,
            surface_snapshot=getattr(prepared, "surface", None),
            request_runtime_root=request_runtime_root,
            runtime_preserve_relpaths=getattr(prepared, "runtime_preserve_relpaths", ()),
        )
        handle.child_pid = child_pid
        handle.child_creation_identity = child_creation_identity
        handle.adopted_child = getattr(transport, "_adopted_child", None)
        self._trace_session_opened(
            handle,
            provider_id=provider_id,
            model_id=model_id,
        )
        # AS19 Stage-2 Slice A: resolve transport-observation lease from
        # providers_api. The lease normalizes TransportObservation values into
        # canonical StatusEvidence. Best-effort — session still opens if this
        # fails (unsupported surface or provider disabled).
        try:
            from audiagentic.components.providers import providers_api
            from audiagentic.foundation.transports.harness_status_observer import (
                StatusObserverRequest,
            )

            _surface_id = (
                getattr(prepared.surface, "surface_id", None)
                if hasattr(prepared, "surface") and prepared.surface is not None
                else None
            )
            if _surface_id is not None:
                _observer_request = StatusObserverRequest(
                    project_root=str(project_root),
                    provider_id=provider_id,
                    surface_id=_surface_id,
                    session_id=session_id,
                    request_id=None,
                    correlation_id=correlation_id,
                )
                _obs_result, _obs_lease = providers_api.open_harness_status_observer(
                    _observer_request,
                    agents_enabled=True,
                )
                if _obs_result.ok and _obs_lease is not None:
                    handle.observer_lease = _obs_lease
                    logger.info(
                        "harness status observer lease acquired",
                        extra={"session-id": session_id, "binding-id": _obs_lease.binding_id},
                    )
                else:
                    logger.debug(
                        "harness status observer not supported for surface",
                        extra={
                            "session-id": session_id,
                            "surface-id": _surface_id,
                            "error-code": _obs_result.error_code,
                        },
                    )
        except Exception:  # noqa: BLE001 — observer is best-effort; don't fail open.
            logger.debug(
                "harness status observer resolution failed",
                extra={"session-id": session_id},
                exc_info=True,
            )
        # AS19 Stage-3: create observer binding for the session.
        # Binding lifecycle is tied to session — created on open, invalidated
        # automatically on close/failure via invalidate_all_for_session.
        try:
            binding_id, _token, _ingress_endpoint = self._observer_ingress.create_observer_binding(
                session_id=session_id,
                project_root=str(project_root),
            )
            handle.observer_binding_id = binding_id
        except AudiaGenticError:
            # Binding already exists (should not happen in normal flow) or
            # runtime error — best-effort; session still opens.
            logger.warning(
                "failed to create observer binding on session open",
                extra={"session-id": session_id},
                exc_info=True,
            )
        self._handles[session_id] = handle
        _publish_session_event(
            SESSION_OPENED_TOPIC,
            {
                "session-id": session_id,
                "execution-profile-id": record["execution-profile-id"],
                "state": "active",
                "provider-id": session_store.session_provider_id(record),
                "model-id": session_store.session_model_id(record),
                # AS17: project foundation process facts into session events.
                "child-pid": child_pid,
                "child-creation-identity": child_creation_identity,
            },
            correlation_id=correlation_id,
        )
        logger.info(
            "gateway session opened",
            extra={"session-id": session_id, "execution-profile-id": execution_profile_id},
        )
        logger.info(
            "gateway open coroutine complete elapsed-ms=%.1f session-id=%s",
            (time.monotonic() - started) * 1000,
            session_id,
            extra={"session-runtime-phase": "open.complete", "correlation-id": correlation_id},
        )
        return record

    async def _resume_session(
        self,
        project_root: Path,
        source_session_id: str,
        *,
        control_id: str,
        execution_context_fingerprint: str | None,
        context_id: str | None,
        agent_definition_id: str | None,
        agent_definition_digest: str | None,
        role_ids: tuple[str, ...] | list[str] | None,
        role_set_digest: str | None,
        execution_profile_digest: str | None,
        effective_capability_digest: str | None,
        model_id: str | None,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        correlation_id: str | None,
        request_runtime_root: Path | None,
        project_name: str | None,
    ) -> dict[str, Any]:
        """AS49: resolve, validate, and dispatch an explicit resume request.

        Never falls back to opening a fresh session on any failure — every
        rejection path raises a typed AudiaGenticError (see
        agents_gateway_session_resume.py for the taxonomy) and records the
        failure under the idempotency key so a replay returns the same
        rejection rather than silently retrying against the provider.
        """
        if self._shutdown:
            raise AudiaGenticError(
                code="CON-AGW-002",
                kind="agents",
                message="session runtime has been shut down",
                details={},
            )

        from audiagentic.components.agents.gateway.session import resume as resume_lib
        from audiagentic.components.providers.providers_api import SurfaceHint

        # ── Idempotency: replay a prior attempt for this exact control id ──
        prior = resume_lib.lookup_resume_attempt(project_root, source_session_id, control_id)
        if prior is not None:
            if prior.get("outcome") == "succeeded" and prior.get("new-session-id"):
                return session_store.read_session_record(project_root, prior["new-session-id"])
            raise AudiaGenticError(
                code=resume_lib.ERR_IDEMPOTENT_REPLAY_OF_FAILURE,
                kind="agents",
                message="this resume control id was already used for a request that failed",
                details={
                    "source-session-id": source_session_id,
                    "prior-error-code": prior.get("error-code"),
                },
            )

        def _record_failure(exc: AudiaGenticError) -> None:
            resume_lib.record_resume_attempt(
                project_root,
                source_session_id,
                control_id,
                outcome="failed",
                error_code=exc.code,
                error_message=exc.message,
            )

        # ── Resolve source record + binding (raw/protected reads) ──
        try:
            source_record = session_store.read_session_record(project_root, source_session_id)
        except AudiaGenticError as exc:
            _record_failure(exc)
            raise
        source_binding = session_store.read_session_binding(project_root, source_session_id)
        requested_composition = {
            "context-id": context_id,
            "agent-definition-id": agent_definition_id,
            "agent-definition-digest": agent_definition_digest,
            "role-ids": list(role_ids) if role_ids is not None else None,
            "role-set-digest": role_set_digest,
            "execution-profile-digest": execution_profile_digest,
            "effective-capability-digest": effective_capability_digest,
        }
        if source_binding:
            for key, requested in requested_composition.items():
                if requested is not None and requested != source_binding.get(key):
                    exc = AudiaGenticError(
                        code="CON-AGW-124",
                        kind="agents",
                        message="requested session composition does not match the source generation",
                        details={"session-id": source_session_id, "field": key},
                    )
                    _record_failure(exc)
                    raise exc
        provider_id = (source_binding or {}).get("provider-id")
        surface_id = (source_binding or {}).get("surface-id")
        if not isinstance(surface_id, str) or not surface_id.strip():
            exc = AudiaGenticError(
                code="CON-AGW-104",
                kind="agents",
                message="session binding has no resolved surface id; cannot resume",
                details={"session-id": source_session_id, "provider-id": provider_id},
            )
            _record_failure(exc)
            raise exc

        from audiagentic.components.providers import providers_api

        surface = providers_api.resolve_session_surface(
            project_root,
            provider_id or "",
            SurfaceHint(surface_id=surface_id),
        )

        try:
            resume_lib.validate_resume_eligibility(
                source_session_id=source_session_id,
                source_state=source_record["state"],
                source_binding=source_binding,
                surface=surface,
                execution_context_fingerprint=execution_context_fingerprint,
            )
        except AudiaGenticError as exc:
            _record_failure(exc)
            raise

        # validate_resume_eligibility rejects None bindings, so this is safe:
        assert source_binding is not None

        # An explicit caller override wins; otherwise resume targets the same
        # model the source session used. Must be resolved before transport
        # prep, not just persisted onto the new record afterward -- prepare_
        # provider_session_transport needs a real model id now to resolve the
        # provider's model selection (VAL-MODEL-002 otherwise).
        resume_model_id = model_id or session_store.session_model_id(source_record)
        successor_session_id = session_store.generate_session_id()

        async def resume_binding_sink(update: Any) -> None:
            # The successor record is created before a resumed GPT-auto turn
            # can publish prompt/assistant message IDs.  Reusing the immutable
            # provider ref makes this an idempotent metadata refresh rather
            # than a new binding generation.
            if not getattr(update, "provider_session_ref", None):
                raise AudiaGenticError(
                    code="CON-AGW-122",
                    kind="agents",
                    message="resumed transport binding update has no provider ref",
                    details={"session-id": successor_session_id},
                )
            if update.provider_session_ref.value != source_binding["provider-session-ref"]:
                raise AudiaGenticError(
                    code="CON-AGW-120",
                    kind="agents",
                    message="resumed transport attempted to replace its provider binding",
                    details={"session-id": successor_session_id},
                )
            session_store.install_initial_provider_binding(
                project_root,
                successor_session_id,
                provider_id=provider_id,
                surface_id=surface_id,
                provider_session_ref=update.provider_session_ref.value,
                metadata=dict(update.metadata),
                # Identity is provider-conversation provenance, not a
                # caller-controlled resume input.  Preserve the immutable
                # source binding value while allowing persistent surfaces to
                # ignore gateway execution-context drift.
                identity_context_fingerprint=source_binding.get(
                    "identity-context-fingerprint"
                ),
                execution_context_fingerprint=execution_context_fingerprint,
                context_id=source_binding.get("context-id"),
                agent_definition_id=source_binding.get("agent-definition-id"),
                agent_definition_digest=source_binding.get("agent-definition-digest"),
                role_ids=source_binding.get("role-ids"),
                role_set_digest=source_binding.get("role-set-digest"),
                execution_profile_digest=source_binding.get("execution-profile-digest"),
                effective_capability_digest=source_binding.get("effective-capability-digest"),
            )

        # AS49: reuse the ORIGINAL request's runtime root, where a provider's
        # own durable session state was preserved on close (see
        # runtime_preserve_relpaths/_cleanup_preserving) instead of deleted --
        # resume_execution_session never establishes a request_runtime_root of
        # its own (unlike ordinary dispatch, it isn't driven by a queued
        # request), so without this PI_CODING_AGENT_DIR would never even be
        # set and pi-acp would fall back to the real, unisolated ~/.pi/agent,
        # which never has the session it's trying to resume. Reusing the same
        # directory (rather than seeding a copy into a fresh one) is also
        # simply correct: it's the same isolated environment continuing, not
        # a new one. The opening request is always request-ids[0] --
        # request_runtime_root is established once at open time and reused
        # for the whole session's life, never recomputed per turn. An
        # explicit caller-supplied request_runtime_root still wins.
        if request_runtime_root is None:
            opening_request_ids = session_store.session_request_ids(source_record)
            if opening_request_ids:
                from audiagentic.components.agents.agents_paths import gateway_request_dir

                request_runtime_root = (
                    gateway_request_dir(project_root, opening_request_ids[0]) / "runtime"
                )

        # ── Dispatch exactly one provider-local resume operation ──
        prepare_kwargs: dict[str, Any] = {
            "provider_id": provider_id,
            "ag_session_id": successor_session_id,
            "binding_sink": resume_binding_sink,
            "surface_hint": SurfaceHint(surface_id=surface_id),
            "model_id": resume_model_id,
            "resume_provider_ref": source_binding["provider-session-ref"],
            # AS30 forbids mutating a generation's binding in place, so
            # provider-session-ref stays frozen at open-time forever; pass the
            # session's own (per-turn-refreshed) provider-metadata alongside
            # it as an opaque supplementary hint -- generic here, only
            # meaningful to whichever provider builder chooses to read it.
            "resume_provider_metadata": session_store.session_provider_metadata(source_record),
            "project_name": project_name,
        }
        if request_runtime_root is not None:
            prepare_kwargs["request_runtime_root"] = request_runtime_root
        prepared = self._provider_prepare_fn(project_root, **prepare_kwargs)
        if prepared.transport is None:
            exc = AudiaGenticError(
                code="CON-AGW-095",
                kind="agents",
                message="resolved session surface is unsupported; cannot resume session",
                details={"provider-id": provider_id, "surface-id": surface_id},
            )
            _record_failure(exc)
            raise exc
        transport = prepared.transport
        try:
            open_result = await transport.open()
        except asyncio.CancelledError:
            await _close_failed_transport(transport)
            raise
        except Exception as exc:  # noqa: BLE001 — provider rejection, not a fallback path
            await _close_failed_transport(transport)
            cause_message = str(exc).strip()
            underlying_details = getattr(exc, "details", None)
            wrapped = AudiaGenticError(
                code="EXT-AGW-118",
                kind="agents",
                message="provider rejected the resume operation",
                details={
                    key: value
                    for key, value in {
                        "provider-id": provider_id,
                        "surface-id": surface_id,
                        "error-type": type(exc).__name__,
                        "error-message": cause_message,
                        # AudiaGenticError from a lower layer already carries
                        # the real reason in its own .details. Surface it here
                        # without emitting a null placeholder.
                        "underlying-details": underlying_details,
                    }.items()
                    if value is not None and value != "" and value != {}
                },
            )
            _record_failure(wrapped)
            raise wrapped from exc

        if open_result.ag_session_id != successor_session_id:
            await _close_failed_transport(transport)
            raise AudiaGenticError(
                code="CON-AGW-121",
                kind="agents",
                message="resumed transport returned a different gateway session id",
                details={"session-id": successor_session_id},
            )
        if open_result.provider_session_ref is None:
            await _close_failed_transport(transport)
            raise AudiaGenticError(
                code="CON-AGW-123",
                kind="agents",
                message="resumed transport did not prove its provider session identity",
                details={"session-id": successor_session_id},
            )
        provider_session_ref = open_result.provider_session_ref.value
        source_provider_ref = source_binding["provider-session-ref"]
        if provider_session_ref != source_provider_ref:
            await _close_failed_transport(transport)
            exc = AudiaGenticError(
                code="CON-AGW-123",
                kind="agents",
                message="resumed transport returned a different provider session identity",
                details={
                    "session-id": successor_session_id,
                    "source-provider-session-ref": source_provider_ref,
                    "returned-provider-session-ref": provider_session_ref,
                },
            )
            _record_failure(exc)
            raise exc

        # ── Build the new generation's record + RESUMED_FROM binding ──
        record = session_store.build_session_record(
            session_id=successor_session_id,
            execution_profile_id=source_record["execution-profile-id"],
            provider_id=provider_id,
            model_id=resume_model_id,
            provider_session_ref=provider_session_ref,
            surface_id=surface_id,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            provider_metadata=dict(open_result.metadata),
            context_id=source_binding.get("context-id"),
            agent_definition_id=source_binding.get("agent-definition-id"),
            agent_definition_digest=source_binding.get("agent-definition-digest"),
            role_ids=source_binding.get("role-ids"),
            role_set_digest=source_binding.get("role-set-digest"),
            execution_profile_digest=source_binding.get("execution-profile-digest"),
            effective_capability_digest=source_binding.get("effective-capability-digest"),
        )
        session_id = record["session-id"]
        record["binding"] = binding_store.resume_binding(
            session_id=session_id,
            provider_id=provider_id,
            surface_id=surface_id,
            provider_ref=provider_session_ref,
            predecessor_binding_id=source_binding["binding-id"],
            ref_namespace=source_binding.get("ref-namespace"),
            identity_context_fingerprint=source_binding.get("identity-context-fingerprint"),
            execution_context_fingerprint=source_binding.get("execution-context-fingerprint"),
        )
        try:
            session_store.write_session_record(project_root, record)
            binding_store.register_open_binding(project_root, record)
        except Exception as exc:
            # Provider resume succeeded but persistence failed: never expose a
            # live new generation the client cannot look up. Detach/close per
            # ownership and remove no provisional index state was written.
            await _close_failed_transport(transport)
            try:
                failed_record = session_store.transition_session_record(
                    project_root,
                    session_id,
                    "failed",
                    updates={"close-reason": "resume-persistence-failed", "closed-at": now_iso_z()},
                )
                binding_store.retire_binding(project_root, failed_record, state="failed")
            except Exception:  # noqa: BLE001 - preserve the original persistence failure
                logger.warning(
                    "failed to roll back resumed session record",
                    extra={"session-id": session_id},
                    exc_info=True,
                )
            wrapped = AudiaGenticError(
                code="IO-AGW-119",
                kind="agents",
                message="resume succeeded at the provider but persisting the new session record failed",
                details={"source-session-id": source_session_id},
            )
            _record_failure(wrapped)
            raise wrapped from exc

        child_pid = getattr(transport, "child_pid", None)
        handle = _SessionHandle(
            session_id=session_id,
            transport=transport,
            project_root=project_root,
            execution_profile_id=source_record["execution-profile-id"],
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            turn_timeout_seconds=turn_timeout_seconds,
            turn_silence_timeout_seconds=turn_silence_timeout_seconds,
            created_clock=self._clock(),
            correlation_id=correlation_id,
            surface_snapshot=surface,
            request_runtime_root=request_runtime_root,
            runtime_preserve_relpaths=getattr(prepared, "runtime_preserve_relpaths", ()),
        )
        handle.child_pid = child_pid
        handle.adopted_child = getattr(transport, "_adopted_child", None)
        # A resumed provider conversation must have the same observation
        # surface as a fresh session.  Reacquire both leases before exposing
        # the handle so lifecycle evidence is not silently weakened by resume.
        try:
            from audiagentic.components.providers import providers_api
            from audiagentic.foundation.transports.harness_status_observer import (
                StatusObserverRequest,
            )

            observer_request = StatusObserverRequest(
                project_root=str(project_root),
                provider_id=provider_id,
                surface_id=surface_id,
                session_id=session_id,
                request_id=None,
                correlation_id=correlation_id,
            )
            observer_result, observer_lease = providers_api.open_harness_status_observer(
                observer_request,
                agents_enabled=True,
            )
            if observer_result.ok and observer_lease is not None:
                handle.observer_lease = observer_lease
        except Exception:  # noqa: BLE001 - observer remains best effort
            logger.debug(
                "harness status observer resolution failed on session resume",
                extra={"session-id": session_id},
                exc_info=True,
            )
        try:
            binding_id, _token, _ingress_endpoint = self._observer_ingress.create_observer_binding(
                session_id=session_id,
                project_root=str(project_root),
            )
            handle.observer_binding_id = binding_id
        except AudiaGenticError:
            logger.warning(
                "failed to create observer binding on session resume",
                extra={"session-id": session_id},
                exc_info=True,
            )
        self._handles[session_id] = handle

        try:
            session_store.record_session_timeline(
                project_root,
                session_id,
                "session.resumed",
                state="active",
                attributes={
                    "source-session-id": source_session_id,
                    "predecessor-binding-id": source_binding["binding-id"],
                    "provider-id": provider_id,
                    "model-id": session_store.session_model_id(record),
                    "correlation-id": correlation_id,
                },
            )
        except Exception:  # noqa: BLE001 — a timeline failure must not fail the resume
            logger.warning(
                "failed to record session.resumed timeline",
                extra={"session-id": session_id},
                exc_info=True,
            )

        resume_lib.record_resume_attempt(
            project_root,
            source_session_id,
            control_id,
            outcome="succeeded",
            new_session_id=session_id,
        )
        _publish_session_event(
            SESSION_RESUMED_TOPIC,
            {
                "session-id": session_id,
                "source-session-id": source_session_id,
                "execution-profile-id": record["execution-profile-id"],
                "state": "active",
                "provider-id": provider_id,
                "model-id": session_store.session_model_id(record),
            },
            correlation_id=correlation_id,
        )
        logger.info(
            "gateway session resumed",
            extra={"session-id": session_id, "source-session-id": source_session_id},
        )
        return record

    def _require_handle(self, session_id: str) -> _SessionHandle:
        handle = self._handles.get(session_id)
        if handle is None:
            raise AudiaGenticError(
                code="RES-AGW-003",
                kind="agents",
                message="session is not active in this gateway process",
                details={"session-id": session_id},
            )
        return handle

    def _lifetime_exceeded(self, handle: _SessionHandle) -> bool:
        cap = handle.max_lifetime_seconds
        return bool(cap) and (self._clock() - handle.created_clock) > cap

    def _trace_session_opened(
        self,
        handle: _SessionHandle,
        *,
        provider_id: str,
        model_id: str | None,
    ) -> None:
        """Emit one bounded launch summary to the gateway service console."""
        surface = handle.surface_snapshot
        surface_ref = getattr(surface, "ref", None)
        surface_id = getattr(surface_ref, "surface_id", None)
        self._console_trace.session_opened(
            session_id=handle.session_id,
            provider_id=provider_id,
            model_id=model_id,
            execution_profile_id=handle.execution_profile_id,
            surface_id=surface_id,
            child_pid=handle.child_pid,
        )

    async def _prompt(
        self,
        project_root: Path,
        session_id: str,
        prompt: str,
        *,
        request_id: str | None,
        correlation_id: str | None,
        activity_relay: Any | None = None,
    ) -> SessionTurnResult:
        handle = self._require_handle(session_id)
        # Turns queue FIFO on the session lock (RV513) — reject only when the
        # backlog itself is full, so back-pressure stays visible.
        if handle.pending >= self._session_queue_max:
            raise AudiaGenticError(
                code="CON-AGW-003",
                kind="agents",
                message="session turn queue is full",
                details={"session-id": session_id, "queue-max": self._session_queue_max},
            )
        if self._lifetime_exceeded(handle):
            raise AudiaGenticError(
                code="CON-AGW-004",
                kind="agents",
                message="session exceeded its max lifetime and is draining; open a new session",
                details={"session-id": session_id},
            )
        handle.pending += 1
        try:
            await handle.turn_lock.acquire()
        finally:
            handle.pending -= 1

        # AS15: signal that the turn actually started — re-acquire profile
        # concurrency slot from idle state (was released while waiting on turn_lock).
        # The acquisition itself is inside the lock-owning try/finally so a
        # cancellation while waiting cannot strand this session's turn lock.
        turn_slot_started = False
        try:
            if request_id is not None:
                from audiagentic.components.agents.gateway.queue.queue import notify_turn_starting

                await notify_turn_starting(request_id)
                turn_slot_started = True
            # Re-validate after the queued wait: the session may have been
            # closed, failed, or aged out while this turn waited its turn.
            if self._handles.get(session_id) is not handle:
                raise AudiaGenticError(
                    code="RES-AGW-003",
                    kind="agents",
                    message="session was closed while this turn was queued",
                    details={"session-id": session_id},
                )
            if self._lifetime_exceeded(handle):
                raise AudiaGenticError(
                    code="CON-AGW-004",
                    kind="agents",
                    message="session exceeded its max lifetime and is draining; open a new session",
                    details={"session-id": session_id},
                )
            if not handle.transport.is_alive():
                await self._fail_session(handle, reason="failed")
                raise AudiaGenticError(
                    code="RES-AGW-003",
                    kind="agents",
                    message="session child process is no longer alive",
                    details={"session-id": session_id},
                )
            session_store.record_session_timeline(
                project_root,
                session_id,
                "session.turn.started",
                state="active",
                attributes={"request-id": request_id, "correlation-id": correlation_id},
            )
            handle.latest_turn_event = {
                "event": "session.turn.started",
                "request-id": request_id,
                "timestamp": now_iso_z(),
            }
            trace_started = (
                self._console_trace.turn_started(
                    request_id=request_id,
                    session_id=session_id,
                    prompt=prompt,
                )
                if request_id is not None
                else self._clock()
            )

            # RV680: every turn gets a cancel signal (so agent_task_cancel can
            # reach it via protocol-level session/cancel) and an activity
            # clock the reaper can watch for in-turn silence.
            handle.current_request_id = request_id
            handle.owning_turn_task = asyncio.current_task()
            handle.turn_closing_deadline = None
            handle.last_event_clock = self._clock()
            # Local cancel token for explicit caller/owner cleanup (AS28 slice 4b-A).
            # The neutral control path (SessionControlAction.CANCEL_TURN) is the
            # protocol-level contract; this local event remains for the fallback
            # cancel path when callers cannot resolve session_id.
            _local_cancel_event = asyncio.Event()
            if request_id is not None:
                self._turn_cancels[request_id] = _local_cancel_event

            def _mark_activity() -> None:
                handle.last_event_clock = self._clock()

            def _record_latest_turn_event(topic: str, payload: dict[str, Any]) -> None:
                handle.latest_turn_event = {
                    "event": topic,
                    "request-id": payload.get("request-id"),
                    "sequence": payload.get("sequence"),
                    "timestamp": now_iso_z(),
                }

            # AS28 slice 4b-A: build the neutral observation sink that feeds
            # the turn-event pipeline (agents_gateway_turn_events.py).
            _on_event_cb = _make_on_event_callback(
                session_id,
                project_root,
                request_id,
                handle.execution_profile_id,
                correlation_id,
                activity_marker=_mark_activity,
                latest_event_recorder=_record_latest_turn_event,
                activity_relay=activity_relay,
            )

            # AS19 Stage-2 Slice B: create per-turn evidence sink with immutable
            # session/request/turn correlation. Validates exact binding, monotonic
            # dedupe, scalar allowlist, redacted timeline append, and publishes
            # agents.turn.status.observed. Best-effort — never raises.
            _evidence_sink = StatusEvidenceSink(
                session_id=session_id,
                request_id=request_id,
                correlation_id=correlation_id,
                project_root=project_root,
            )

            async def _observation_sink(obs):
                # AS19 Stage-2 Slice A: thread TransportObservation through the
                # observer lease (if one was resolved). The lease normalizes it
                # into canonical StatusEvidence. Best-effort — never block or
                # raise in the observation path.
                if handle.observer_lease is not None:
                    try:
                        status_evidence = handle.observer_lease.observe_transport(obs)
                        if status_evidence is not None:
                            # AS19 Stage-2 Slice B: accept through the evidence sink
                            # (validates binding, monotonic dedupe, scalar allowlist,
                            # redacted timeline append, agents.turn.status.observed).
                            _sink_result = _evidence_sink.accept(status_evidence)
                            if isinstance(_sink_result, RejectedEvidence):
                                logger.debug(
                                    "evidence sink rejected",
                                    extra={
                                        "session-id": session_id,
                                        "reason": _sink_result.reason,
                                    },
                                )
                            # AS21 consumer slice: forward ONLY accepted evidence
                            # into the ephemeral projection registry. Rejected
                            # evidence (duplicate, lower sequence, binding mismatch)
                            # must not change the lifecycle decision.
                            elif isinstance(_sink_result, AcceptedEvidence):
                                self._evidence_projection.accept(
                                    _sink_result.status_evidence,
                                )
                    except Exception:  # noqa: BLE001 — observer must never break turns.
                        logger.debug(
                            "observer lease observe_transport failed",
                            extra={"session-id": session_id},
                            exc_info=True,
                        )
                # Pass TransportObservation directly to the turn-event pipeline.
                # No ACP-specific reconstruction needed.
                result = _on_event_cb(obs)
                if result is not None:
                    await result
                if request_id is not None:
                    kind = getattr(getattr(obs, "kind", None), "value", None) or getattr(obs, "kind", "unknown")
                    self._console_trace.progress(
                        request_id=request_id,
                        session_id=session_id,
                        kind=str(kind),
                        sequence=getattr(obs, "sequence", None),
                        started=trace_started,
                    )

            # AS28 slice 4b-A: call transport.prompt() with the neutral contract.
            # Include cancel_token so the transport can check it for cancellation.
            session_prompt = SessionPrompt(
                turn_id=request_id or "turn-0",
                body=prompt,
                cancel_token=_local_cancel_event if request_id is not None else None,
            )
            try:
                # Call the neutral seam: AgentSessionTransport.prompt().
                # A configured timeout is retained as a provider/profile
                # observation setting, but never converted to a local kill.
                # The neutral transport decides any provider-owned deadline.
                result = await handle.transport.prompt(session_prompt, _observation_sink)
            except Exception as exc:
                if request_id is not None:
                    self._console_trace.failed(
                        request_id=request_id,
                        session_id=session_id,
                        error_code=getattr(exc, "code", None),
                        error_type=type(exc).__name__,
                        started=trace_started,
                    )
                # A provider may have an explicit recovery state machine.  In
                # that case retain the live handle and its browser/session
                # binding; all other transports keep the historical terminal
                # failure behaviour.
                if self._retain_after_turn_failure(handle):
                    try:
                        session_store.record_session_timeline(
                            project_root,
                            session_id,
                            "session.turn.failed",
                            state="active",
                            attributes={
                                "request-id": request_id,
                                "recoverable": True,
                            },
                        )
                    except Exception:  # noqa: BLE001 - diagnostics must not mask turn failure
                        logger.debug(
                            "failed to record recoverable turn failure",
                            extra={"session-id": session_id, "request-id": request_id},
                            exc_info=True,
                        )
                else:
                    await self._fail_session(handle, reason="failed")
                raise
            finally:
                handle.last_activity_clock = self._clock()
                handle.current_request_id = None
                handle.owning_turn_task = None
                handle.turn_closing_deadline = None
                if request_id is not None:
                    self._turn_cancels.pop(request_id, None)
        finally:
            try:
                if request_id is not None and turn_slot_started:
                    from audiagentic.components.agents.gateway.queue.queue import notify_turn_done

                    await notify_turn_done(request_id)
            finally:
                handle.turn_lock.release()
        if request_id is not None:
            final_output = getattr(result, "final_summary", None)
            result_error_code = getattr(result, "error_code", None)
            self._console_trace.finished(
                request_id=request_id,
                session_id=session_id,
                outcome=("failed" if result_error_code else result.stop_reason),
                output=final_output,
                error_code=result_error_code,
                started=trace_started,
            )
        if request_id is not None:
            session_store.record_session_turn(
                project_root,
                session_id,
                request_id,
                provider_metadata=dict(getattr(result, "metadata", {}) or {}) or None,
            )
        # SH15: record dropped-events at turn end for richer progress summary
        turn_end_attrs: dict[str, Any] = {
            "request-id": request_id,
            "stop-reason": result.stop_reason,
            "correlation-id": correlation_id,
        }
        if result.dropped_observations:
            turn_end_attrs["dropped-events"] = result.dropped_observations
        if result.observations_delivered or result.dropped_observations:
            turn_end_attrs["total-events"] = (
                result.observations_delivered + result.dropped_observations
            )
        session_store.record_session_timeline(
            project_root,
            session_id,
            "session.turn.finished",
            state="active",
            attributes=turn_end_attrs,
        )
        try:
            turn_record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError:
            turn_record = None
        _publish_session_event(
            SESSION_TURN_FINISHED_TOPIC,
            {
                "session-id": session_id,
                "execution-profile-id": handle.execution_profile_id,
                "state": "active",
                "provider-id": session_store.session_provider_id(turn_record)
                if turn_record
                else None,
                "model-id": session_store.session_model_id(turn_record) if turn_record else None,
                "request-id": request_id,
                "turn-count": session_store.session_turn_count(turn_record)
                if turn_record
                else None,
                "stop-reason": result.stop_reason,
            },
            correlation_id=correlation_id,
        )
        return result

    async def _fail_session(self, handle: _SessionHandle, *, reason: str) -> None:
        # Reaper and owning turn can observe the same transport failure. The
        # first caller owns the existing store/transport cleanup; later callers
        # return so a terminal session/event is never duplicated.
        if handle.failure_started:
            return
        handle.failure_started = True
        self._handles.pop(handle.session_id, None)
        try:
            await handle.transport.close()
        except Exception:  # noqa: BLE001 - provider cleanup is best effort
            # A provider cleanup failure must not strand the durable session
            # in an owned in-memory state.  Persist the terminal session below
            # and let the next explicit resume establish a fresh handle.
            logger.warning(
                "provider transport close failed while failing session",
                extra={"session-id": handle.session_id},
                exc_info=True,
            )
        finally:
            self._cleanup_handle_runtime(handle)
        try:
            record = session_store.read_session_record(handle.project_root, handle.session_id)
            if record["state"] not in session_store.SESSION_TERMINAL_STATES:
                updated = session_store.transition_session_record(
                    handle.project_root,
                    handle.session_id,
                    "failed",
                    updates={"close-reason": reason, "closed-at": now_iso_z()},
                )
                binding_store.retire_binding(handle.project_root, updated, state="failed")
            # AS19 Stage-2: invalidate observer bindings on session failure.
            self._observer_ingress.invalidate_all_for_session(handle.session_id)
            _publish_session_event(
                SESSION_FAILED_TOPIC,
                {
                    "session-id": handle.session_id,
                    "execution-profile-id": record["execution-profile-id"],
                    "state": "failed",
                    "provider-id": session_store.session_provider_id(record),
                    "model-id": session_store.session_model_id(record),
                    "close-reason": reason,
                    "turn-count": session_store.session_turn_count(record),
                },
                correlation_id=handle.correlation_id,
            )
        except AudiaGenticError:
            logger.warning(
                "failed to persist session failure",
                extra={"session-id": handle.session_id},
                exc_info=True,
            )

    @staticmethod
    def _retain_after_turn_failure(handle: _SessionHandle) -> bool:
        """Ask a provider state machine whether a failed turn is resumable."""
        try:
            disposition = handle.transport.turn_failure_disposition()
            return SessionFailureDisposition(disposition) is SessionFailureDisposition.RETAIN
        except (AttributeError, TypeError, ValueError):
            # Existing transports and test doubles predate this optional
            # capability; their safe default is to terminate the session.
            return False

    async def _close(
        self,
        project_root: Path,
        session_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        handle = self._handles.get(session_id)
        if handle is not None and reason != "shutdown" and not handle.quiescent():
            # An explicit client close is authoritative.  Do not wait for a
            # provider recovery turn to become quiescent: GPT-auto can keep an
            # unresolved turn alive (and recreate its browser tab) forever.
            # Terminalize and remove the gateway handle first, then cancel and
            # best-effort close the provider transport.  This prevents queued
            # continuations and recovery from retaining a queue/session lock.
            if reason == "client-request":
                return await self._close_client_request(project_root, session_id, handle)
            deadline = self._clock() + _CLOSE_TIMEOUT_SECONDS
            while not handle.quiescent() and self._clock() < deadline:
                await asyncio.sleep(0.05)
            if not handle.quiescent():
                raise AudiaGenticError(
                    code="CON-AGW-004",
                    kind="agents",
                    message="session is busy and could not be closed safely",
                    details={"session-id": session_id},
                )
        handle = self._handles.pop(session_id, None)
        if handle is not None:
            await handle.transport.close()
            self._cleanup_handle_runtime(handle)
        try:
            record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError:
            if handle is None:
                raise
            record = None
        if record is not None and record["state"] not in session_store.SESSION_TERMINAL_STATES:
            new_state = "expired" if reason in ("idle-timeout", "max-lifetime") else "closed"
            record = session_store.transition_session_record(
                project_root,
                session_id,
                new_state,
                updates={"close-reason": reason, "closed-at": now_iso_z()},
            )
            binding_store.retire_binding(project_root, record, state=new_state)
            # AS19 Stage-2: invalidate observer bindings on session close.
            self._observer_ingress.invalidate_all_for_session(session_id)
            # AS21 consumer slice: clear evidence projection for this session.
            self._evidence_projection.clear_for_session(session_id)
            session_store.record_session_timeline(
                project_root,
                session_id,
                "session.closed",
                state=record["state"],
                attributes={
                    "close-reason": reason,
                    "correlation-id": handle.correlation_id if handle else None,
                },
            )
            topic = SESSION_EXPIRED_TOPIC if new_state == "expired" else SESSION_CLOSED_TOPIC
            _publish_session_event(
                topic,
                {
                    "session-id": session_id,
                    "execution-profile-id": record["execution-profile-id"],
                    "state": new_state,
                    "provider-id": session_store.session_provider_id(record),
                    "model-id": session_store.session_model_id(record),
                    "close-reason": reason,
                    "turn-count": session_store.session_turn_count(record),
                },
                correlation_id=handle.correlation_id if handle else None,
            )
        logger.info(
            "gateway session closed", extra={"session-id": session_id, "close-reason": reason}
        )
        return record if record is not None else {"session-id": session_id, "state": "closed"}

    async def _close_client_request(
        self,
        project_root: Path,
        session_id: str,
        handle: _SessionHandle,
    ) -> dict[str, Any]:
        """Authoritatively close a busy session on explicit client request.

        The durable terminal transition and handle removal happen before
        touching the provider transport.  This is deliberately fail-closed:
        an unresolved provider turn must not keep the session eligible for
        recovery or hold a queue lock while browser cleanup is attempted.
        """
        self._handles.pop(session_id, None)
        owning_task = handle.owning_turn_task
        if owning_task is not None and not owning_task.done():
            owning_task.cancel()

        try:
            record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError:
            record = None
        if record is not None and record["state"] not in session_store.SESSION_TERMINAL_STATES:
            record = session_store.transition_session_record(
                project_root,
                session_id,
                "closed",
                updates={"close-reason": "client-request", "closed-at": now_iso_z()},
            )
            binding_store.retire_binding(project_root, record, state="closed")
            self._observer_ingress.invalidate_all_for_session(session_id)
            self._evidence_projection.clear_for_session(session_id)
            session_store.record_session_timeline(
                project_root,
                session_id,
                "session.closed",
                state="closed",
                attributes={
                    "close-reason": "client-request",
                    "correlation-id": handle.correlation_id,
                },
            )
            _publish_session_event(
                SESSION_CLOSED_TOPIC,
                {
                    "session-id": session_id,
                    "execution-profile-id": record["execution-profile-id"],
                    "state": "closed",
                    "provider-id": session_store.session_provider_id(record),
                    "model-id": session_store.session_model_id(record),
                    "close-reason": "client-request",
                    "turn-count": session_store.session_turn_count(record),
                },
                correlation_id=handle.correlation_id,
            )

        try:
            await asyncio.wait_for(handle.transport.close(), timeout=5.0)
        except Exception:  # noqa: BLE001 - provider cleanup is best effort
            logger.warning(
                "provider transport close failed after authoritative session close",
                extra={"session-id": session_id},
                exc_info=True,
            )
        self._cleanup_handle_runtime(handle)
        logger.info(
            "gateway session closed", extra={"session-id": session_id, "close-reason": "client-request"}
        )
        return record if record is not None else {"session-id": session_id, "state": "closed"}

    @staticmethod
    def _cleanup_handle_runtime(handle: _SessionHandle) -> None:
        if handle.request_runtime_root is None:
            return
        import shutil

        try:
            if handle.runtime_preserve_relpaths:
                preserve_abs = {
                    (handle.request_runtime_root / relpath).resolve()
                    for relpath in handle.runtime_preserve_relpaths
                }
                _cleanup_preserving(handle.request_runtime_root, preserve_abs)
            else:
                shutil.rmtree(handle.request_runtime_root, ignore_errors=True)
        except OSError:  # noqa: BLE001 — cleanup is best-effort
            logger.warning(
                "failed to clean up handle runtime root",
                extra={"path": str(handle.request_runtime_root)},
                exc_info=True,
            )

    async def _close_all(self, *, reason: str) -> None:
        for session_id in list(self._handles):
            handle = self._handles.get(session_id)
            if handle is None:
                continue
            try:
                await self._close(handle.project_root, session_id, reason=reason)
            except Exception:  # noqa: BLE001 — close every session regardless
                logger.warning(
                    "session close failed during close-all",
                    extra={"session-id": session_id},
                    exc_info=True,
                )

    async def _reaper(self) -> None:
        """Periodic sweep: idle timeouts, max lifetime, dead children."""
        while True:
            await asyncio.sleep(self._reap_interval)
            try:
                await self._reap_once()
            except Exception:  # noqa: BLE001 — the reaper must never die
                logger.error("session reaper sweep failed", exc_info=True)

    async def _reap_once(self) -> None:
        """Sweep quiescent sessions only — a session that is processing or has
        queued turns is NEVER closed by the reaper (RV513). A session past its
        max lifetime stops accepting new turns (_prompt raises CON-AGW-004),
        drains, and is closed on the first sweep that finds it quiescent.
        A bound of 0 disables that bound entirely."""
        now = self._clock()
        for session_id in list(self._handles):
            handle = self._handles.get(session_id)
            if handle is None:
                continue
            if not handle.quiescent():
                adopted = handle.adopted_child
                observation = None
                if adopted is not None:
                    try:
                        from audiagentic.foundation.system.adopted_process import (
                            AdoptedChild,
                            observe_child,
                        )

                        if isinstance(adopted, AdoptedChild):
                            observation = observe_child(adopted.evidence)
                    except Exception:  # noqa: BLE001 — unknown remains non-actionable
                        logger.debug(
                            "failed to observe owned session child",
                            extra={"session-id": session_id},
                            exc_info=True,
                        )
                liveness = orphan_lib.OwnedTurnLiveness(
                    request_id=handle.current_request_id,
                    turn_task=handle.owning_turn_task,
                    turn_active=handle.turn_lock.locked(),
                    adopted_child=adopted,
                    closing_deadline=handle.turn_closing_deadline,
                    last_event_clock=handle.last_event_clock,
                )
                if orphan_lib.is_proven_owned_turn_dead(liveness, observation, now):
                    # Set before any await so repeated sweeps cannot emit a
                    # second orphan event or issue duplicate cleanup.
                    if not handle.orphan_cleanup_started:
                        handle.orphan_cleanup_started = True
                        session_store.record_session_timeline(
                            handle.project_root,
                            session_id,
                            "session.orphaned",
                            state="active",
                            attributes={
                                "request-id": handle.current_request_id,
                                "reason": "proven-owned-child-dead",
                                "correlation-id": handle.correlation_id,
                            },
                        )
                        _publish_session_event(
                            SESSION_ORPHANED_TOPIC,
                            {
                                "session-id": session_id,
                                "execution-profile-id": handle.execution_profile_id,
                                "state": "active",
                                "request-id": handle.current_request_id,
                            },
                            correlation_id=handle.correlation_id,
                        )
                        owning_task = handle.owning_turn_task
                        await self._fail_session(handle, reason="orphaned")
                        if owning_task is not None and not owning_task.done():
                            owning_task.cancel()
                    continue
                # RV680/AS26: read-only inspection of busy sessions. When the
                # profile declared an expected event cadence, prolonged
                # in-turn silence is a configured timeout policy, not proof
                # of process death. Otherwise unknown stays conservative and
                # the turn deadline is the only in-turn bound.
                silence_cap = handle.turn_silence_timeout_seconds
                if (
                    silence_cap
                    and handle.turn_lock.locked()
                    and (now - handle.last_event_clock) > silence_cap
                ):
                    logger.warning(
                        "session turn silence timeout: no transport events within bound",
                        extra={
                            "session-id": session_id,
                            "silence-timeout-seconds": silence_cap,
                            "request-id": handle.current_request_id,
                        },
                    )
                    try:
                        session_store.record_session_timeline(
                            handle.project_root,
                            session_id,
                            "session.turn.silence-timeout",
                            state="active",
                            attributes={
                                "request-id": handle.current_request_id,
                                "silence-timeout-seconds": silence_cap,
                            },
                        )
                    except Exception:  # noqa: BLE001 — reaper must not die
                        logger.debug("failed to record stall timeline", exc_info=True)
                    # Silence is a diagnostic suspicion only. Tool calls and
                    # remote provider waits need not produce local events, so
                    # it cannot terminate a session or release a slot.
                continue
            if not handle.transport.is_alive():
                await self._fail_session(handle, reason="failed")
                continue
            if self._lifetime_exceeded(handle):
                await self._close(handle.project_root, session_id, reason="max-lifetime")
                continue
            idle = now - handle.last_activity_clock
            if handle.idle_timeout_seconds and idle > handle.idle_timeout_seconds:
                await self._close(handle.project_root, session_id, reason="idle-timeout")


_SESSION_RUNTIME: SessionRuntime | None = None
_SESSION_RUNTIME_LOCK = threading.Lock()


def get_session_runtime() -> SessionRuntime:
    """Return the process-wide SessionRuntime, creating it on first use."""
    global _SESSION_RUNTIME
    with _SESSION_RUNTIME_LOCK:
        if _SESSION_RUNTIME is None:
            _SESSION_RUNTIME = SessionRuntime()
            atexit.register(_SESSION_RUNTIME.shutdown)
        return _SESSION_RUNTIME


def peek_session_runtime() -> SessionRuntime | None:
    """Return the SessionRuntime only if one already exists (no side effects).

    For callers (e.g. the queue cancel path) that must signal live sessions
    but must never spin up a runtime as a side effect of a cancel.
    """
    with _SESSION_RUNTIME_LOCK:
        return _SESSION_RUNTIME


def reset_session_runtime() -> None:
    """Forget a shut-down singleton so a later composed host starts cleanly."""
    global _SESSION_RUNTIME
    with _SESSION_RUNTIME_LOCK:
        if _SESSION_RUNTIME is not None and _SESSION_RUNTIME._shutdown:
            _SESSION_RUNTIME = None
