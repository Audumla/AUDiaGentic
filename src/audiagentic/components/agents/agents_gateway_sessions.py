"""Agent LLM Gateway live session runtime (plan agent-sessions AS02).

Owns live agent sessions inside the gateway process: one background daemon
thread running an asyncio event loop hosts every AcpSessionTransport; sync
gateway code talks to it via run_coroutine_threadsafe. Mirrors the
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

This module is generic: it knows launches and transports, never providers,
coding, or planning. Provider resolution lives in dispatch (AS04).
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_event_topics import (
    SESSION_CLOSED_TOPIC,
    SESSION_EXPIRED_TOPIC,
    SESSION_FAILED_TOPIC,
    SESSION_OPENED_TOPIC,
    SESSION_TURN_FINISHED_TOPIC,
)
from audiagentic.components.agents.agents_gateway_turn_events import (
    _make_on_event_callback,
    _publish_session_event,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports import AcpLaunch, AcpResult, AcpSessionTransport

logger = logging.getLogger(__name__)

# Gateway defaults — overridable per session at open time (config over code:
# dispatch resolves per-profile params session-idle-timeout-seconds /
# session-max-lifetime-seconds before calling open_session).
DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS = 900.0  # 15 min without a turn
DEFAULT_SESSION_MAX_LIFETIME_SECONDS = 14_400.0  # 4 h; 0 disables the cap
# RV680: a session turn with no deadline wedges the profile's compute slot
# forever when the harness hangs. Generous default; 0 disables the bound.
DEFAULT_TURN_TIMEOUT_SECONDS = 3_600.0
# In-turn event-silence watchdog: 0 (default) disables. Silence is a configured
# policy timeout for profiles that declare an expected event cadence; it is not
# proof of process death or orphaning.
DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS = 0.0
DEFAULT_REAP_INTERVAL_SECONDS = 30.0
# Max turns waiting on one session's FIFO before new prompts are rejected —
# keeps back-pressure visible instead of building an unbounded backlog (RV513).
DEFAULT_SESSION_QUEUE_MAX = 8
_OPEN_TIMEOUT_SECONDS = 120.0
_CLOSE_TIMEOUT_SECONDS = 30.0


class _SessionHandle:
    """Loop-side state for one live session. Touched only on the loop thread."""

    def __init__(
        self,
        *,
        session_id: str,
        transport: Any,
        project_root: Path,
        agent_profile_id: str,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        created_clock: float,
        correlation_id: str | None,
    ) -> None:
        self.session_id = session_id
        self.transport = transport
        self.project_root = project_root
        self.agent_profile_id = agent_profile_id
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_lifetime_seconds = max_lifetime_seconds
        self.turn_timeout_seconds = turn_timeout_seconds
        self.turn_silence_timeout_seconds = turn_silence_timeout_seconds
        self.created_clock = created_clock
        self.correlation_id = correlation_id
        self.last_activity_clock = created_clock
        # In-turn liveness: refreshed by every transport event during a turn
        # (RV680 silence watchdog); meaningful only while a turn is running.
        self.last_event_clock = created_clock
        self.current_request_id: str | None = None
        # AS17/RV681: OS facts for the transport child, captured at open.
        self.child_pid: int | None = None
        self.child_creation_identity: str | None = None
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
    ) -> None:
        """Update lifetime bounds on an existing handle.

        Only mutates the fields that are explicitly provided (not None).
        Called by dispatch when continuing a session with keep-alive and new
        policy values; best-effort — no durable write here, just the in-memory
        handle (the persisted record retains its original values).
        """
        if idle_timeout_seconds is not None:
            self.idle_timeout_seconds = idle_timeout_seconds
        if max_lifetime_seconds is not None:
            self.max_lifetime_seconds = max_lifetime_seconds


TransportFactory = Callable[..., Any]
"""Builds a transport from (launch, cwd=...). Injected for tests; defaults to
AcpSessionTransport."""


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
        transport_factory: TransportFactory | None = None,
        session_queue_max: int = DEFAULT_SESSION_QUEUE_MAX,
    ) -> None:
        self._clock = clock
        self._reap_interval = reap_interval_seconds
        self._session_queue_max = session_queue_max
        # compact_events: the gateway consumes text/kind/counts only — raw
        # update payloads are never persisted or surfaced, so buffering them
        # is pure memory cost and what exhausts the byte budget on long
        # implementation turns (MA29 truncation finding).
        self._transport_factory = transport_factory or (
            lambda launch, cwd: AcpSessionTransport(launch, cwd=cwd, compact_events=True)
        )
        self._handles: dict[str, _SessionHandle] = {}
        # request-id → cancel event for the turn currently owning that request
        # (loop-thread only). request_cancel() sets these threadsafe (RV680).
        self._turn_cancels: dict[str, asyncio.Event] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._shutdown = False

    # ── loop plumbing ────────────────────────────────────────────

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None and self._loop_thread is not None and self._loop_thread.is_alive():
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
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)

    # ── public sync API ──────────────────────────────────────────

    def open_session(
        self,
        project_root: Path,
        *,
        agent_profile_id: str,
        launch: AcpLaunch,
        provider_id: str | None = None,
        model_id: str | None = None,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
        turn_timeout_seconds: float | None = None,
        turn_silence_timeout_seconds: float | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Open a live session; returns the persisted session record."""
        return self._call(
            self._open_session(
                project_root,
                agent_profile_id=agent_profile_id,
                launch=launch,
                provider_id=provider_id,
                model_id=model_id,
                # None → gateway default; an explicit 0 DISABLES the bound
                # (needed for long-lived remote-control sessions, RV513).
                idle_timeout_seconds=(
                    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS
                    if idle_timeout_seconds is None else idle_timeout_seconds
                ),
                max_lifetime_seconds=(
                    DEFAULT_SESSION_MAX_LIFETIME_SECONDS
                    if max_lifetime_seconds is None else max_lifetime_seconds
                ),
                turn_timeout_seconds=(
                    DEFAULT_TURN_TIMEOUT_SECONDS
                    if turn_timeout_seconds is None else turn_timeout_seconds
                ),
                turn_silence_timeout_seconds=(
                    DEFAULT_TURN_SILENCE_TIMEOUT_SECONDS
                    if turn_silence_timeout_seconds is None
                    else turn_silence_timeout_seconds
                ),
                correlation_id=correlation_id,
            ),
            timeout=_OPEN_TIMEOUT_SECONDS,
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
    ) -> AcpResult:
        """Run one turn on a live session; refreshes its idle clock."""
        return self._call(
            self._prompt(
                project_root,
                session_id,
                prompt,
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            timeout=timeout_seconds,
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

    def update_session_bounds(
        self,
        session_id: str,
        *,
        idle_timeout_seconds: float | None = None,
        max_lifetime_seconds: float | None = None,
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
            )

        self._call(_update(), timeout=10)

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

    def request_cancel(self, request_id: str) -> bool:
        """Signal protocol-level cancel to the turn owning *request_id*.

        Best-effort and threadsafe (RV680): returns True when the signal was
        scheduled on the session loop; the turn observes it via the transport's
        cancel_signal race and finishes with stop_reason 'cancelled'. A
        request not currently in a turn is a no-op.
        """
        with self._loop_lock:
            loop = self._loop
        if loop is None or not loop.is_running():
            return False

        def _set() -> None:
            event = self._turn_cancels.get(request_id)
            if event is not None:
                event.set()

        loop.call_soon_threadsafe(_set)
        return True

    def shutdown(self) -> None:
        """Close every live session and stop accepting new ones. Idempotent."""
        with self._loop_lock:
            self._shutdown = True
            loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._close_all(reason="shutdown"), loop
            ).result(timeout=_CLOSE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 — shutdown must never raise
            logger.warning("session runtime shutdown incomplete", exc_info=True)

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
        return {
            "available": True,
            "pending-turns": handle.pending,
            "turn-active": handle.turn_lock.locked(),
            "current-request-id": handle.current_request_id,
            "child-pid": handle.child_pid,
        }

    async def _open_session(
        self,
        project_root: Path,
        *,
        agent_profile_id: str,
        launch: AcpLaunch,
        provider_id: str | None,
        model_id: str | None,
        idle_timeout_seconds: float,
        max_lifetime_seconds: float,
        turn_timeout_seconds: float,
        turn_silence_timeout_seconds: float,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        if self._shutdown:
            raise AudiaGenticError(
                code="CON-AGW-002",
                kind="agents",
                message="session runtime has been shut down",
                details={},
            )
        transport = self._transport_factory(launch, cwd=project_root)
        provider_session_ref = await transport.open()

        record = session_store.build_session_record(
            agent_profile_id=agent_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            provider_session_ref=str(provider_session_ref) if provider_session_ref else None,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
        )
        session_id = record["session-id"]
        try:
            session_store.write_session_record(project_root, record)
            binding_store.register_open_binding(project_root, record)
        except Exception:
            # Never leak a child because bookkeeping failed.
            await transport.close()
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
                child_evidence_available = isinstance(
                    adopted_token, AdoptedChild
                ) and adopted_token.evidence is not None
            except Exception:  # noqa: BLE001 — evidence check is best-effort
                pass
        try:
            session_store.record_session_timeline(
                project_root, session_id, "session.opened", state="active",
                attributes={
                    "agent-profile-id": agent_profile_id,
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
            agent_profile_id=agent_profile_id,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            turn_timeout_seconds=turn_timeout_seconds,
            turn_silence_timeout_seconds=turn_silence_timeout_seconds,
            created_clock=self._clock(),
            correlation_id=correlation_id,
        )
        handle.child_pid = child_pid
        handle.child_creation_identity = child_creation_identity
        self._handles[session_id] = handle
        _publish_session_event(SESSION_OPENED_TOPIC, {
            "session-id": session_id,
            "agent-profile-id": record["agent-profile-id"],
            "state": "active",
            "provider-id": record.get("provider-id"),
            "model-id": record.get("model-id"),
            # AS17: project foundation process facts into session events.
            "child-pid": child_pid,
            "child-creation-identity": child_creation_identity,
        }, correlation_id=correlation_id)
        logger.info("gateway session opened", extra={"session-id": session_id, "agent-profile-id": agent_profile_id})
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

    async def _prompt(
        self,
        project_root: Path,
        session_id: str,
        prompt: str,
        *,
        request_id: str | None,
        correlation_id: str | None,
    ) -> AcpResult:
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
        if request_id is not None:
            from audiagentic.components.agents.agents_gateway_queue import notify_turn_starting

            await notify_turn_starting(request_id)
        try:
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
                project_root, session_id, "session.turn.started", state="active",
                attributes={"request-id": request_id, "correlation-id": correlation_id},
            )

            # RV680: every turn gets a cancel signal (so agent_llm_cancel can
            # reach it via protocol-level session/cancel) and an activity
            # clock the reaper can watch for in-turn silence.
            handle.current_request_id = request_id
            handle.last_event_clock = self._clock()
            cancel_event = asyncio.Event()
            if request_id is not None:
                self._turn_cancels[request_id] = cancel_event

            def _mark_activity() -> None:
                handle.last_event_clock = self._clock()

            # AS18: wire on_event callback for intra-turn visibility
            on_event_cb = _make_on_event_callback(
                session_id, project_root, request_id, handle.agent_profile_id, correlation_id,
                activity_marker=_mark_activity,
            )
            try:
                prompt_coro = handle.transport.prompt(
                    prompt, on_event=on_event_cb, cancel_signal=cancel_event
                )
                if handle.turn_timeout_seconds:
                    # RV680: bound the turn so a wedged harness cannot hold the
                    # profile compute slot forever. Timeout is terminal for the
                    # session — the child's protocol state is unknowable after
                    # an abandoned turn.
                    result = await asyncio.wait_for(
                        prompt_coro, timeout=handle.turn_timeout_seconds
                    )
                else:
                    result = await prompt_coro
            except TimeoutError:
                await self._fail_session(handle, reason="turn-timeout")
                raise AudiaGenticError(
                    code="TO-AGW-090",
                    kind="agents",
                    message="session turn exceeded its deadline",
                    details={
                        "session-id": session_id,
                        "turn-timeout-seconds": handle.turn_timeout_seconds,
                    },
                ) from None
            except Exception:
                # Transport marks itself dead on turn failure; reflect it durably.
                await self._fail_session(handle, reason="failed")
                raise
            finally:
                handle.last_activity_clock = self._clock()
                handle.current_request_id = None
                if request_id is not None:
                    self._turn_cancels.pop(request_id, None)
        finally:
            try:
                if request_id is not None:
                    from audiagentic.components.agents.agents_gateway_queue import notify_turn_done

                    await notify_turn_done(request_id)
            finally:
                handle.turn_lock.release()
        if request_id is not None:
            session_store.record_session_turn(project_root, session_id, request_id)
        # SH15: record dropped-events and callback-health at turn end for
        # richer progress summary
        turn_end_attrs: dict[str, Any] = {
            "request-id": request_id,
            "stop-reason": result.stop_reason,
            "correlation-id": correlation_id,
        }
        if result.dropped_events is not None:
            turn_end_attrs["dropped-events"] = result.dropped_events
        if result.total_events is not None:
            turn_end_attrs["total-events"] = result.total_events
        if result.callback_disabled is not None:
            turn_end_attrs["callback-disabled"] = bool(result.callback_disabled)
        session_store.record_session_timeline(
            project_root, session_id, "session.turn.finished", state="active",
            attributes=turn_end_attrs,
        )
        try:
            turn_record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError:
            turn_record = None
        _publish_session_event(SESSION_TURN_FINISHED_TOPIC, {
            "session-id": session_id,
            "agent-profile-id": handle.agent_profile_id,
            "state": "active",
            "provider-id": turn_record.get("provider-id") if turn_record else None,
            "model-id": turn_record.get("model-id") if turn_record else None,
            "request-id": request_id,
            "turn-count": turn_record.get("turn-count") if turn_record else None,
            "stop-reason": result.stop_reason,
        }, correlation_id=correlation_id)
        return result

    async def _fail_session(self, handle: _SessionHandle, *, reason: str) -> None:
        self._handles.pop(handle.session_id, None)
        await handle.transport.close()
        try:
            record = session_store.read_session_record(handle.project_root, handle.session_id)
            if record["state"] not in session_store.SESSION_TERMINAL_STATES:
                updated = session_store.transition_session_record(
                    handle.project_root, handle.session_id, "failed",
                    updates={"close-reason": reason, "closed-at": now_iso_z()},
                )
                binding_store.retire_binding(handle.project_root, updated, state="failed")
                _publish_session_event(SESSION_FAILED_TOPIC, {
                    "session-id": handle.session_id,
                    "agent-profile-id": record["agent-profile-id"],
                    "state": "failed",
                    "provider-id": record.get("provider-id"),
                    "model-id": record.get("model-id"),
                    "close-reason": reason,
                    "turn-count": record.get("turn-count"),
                }, correlation_id=handle.correlation_id)
        except AudiaGenticError:
            logger.warning("failed to persist session failure", extra={"session-id": handle.session_id}, exc_info=True)

    async def _close(
        self,
        project_root: Path,
        session_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        handle = self._handles.pop(session_id, None)
        if handle is not None:
            await handle.transport.close()
        try:
            record = session_store.read_session_record(project_root, session_id)
        except AudiaGenticError:
            if handle is None:
                raise
            record = None
        if record is not None and record["state"] not in session_store.SESSION_TERMINAL_STATES:
            new_state = "expired" if reason in ("idle-timeout", "max-lifetime") else "closed"
            record = session_store.transition_session_record(
                project_root, session_id, new_state,
                updates={"close-reason": reason, "closed-at": now_iso_z()},
            )
            binding_store.retire_binding(project_root, record, state=new_state)
            session_store.record_session_timeline(
                project_root, session_id, "session.closed", state=record["state"],
                attributes={
                    "close-reason": reason,
                    "correlation-id": handle.correlation_id if handle else None,
                },
            )
            topic = SESSION_EXPIRED_TOPIC if new_state == "expired" else SESSION_CLOSED_TOPIC
            _publish_session_event(topic, {
                "session-id": session_id,
                "agent-profile-id": record["agent-profile-id"],
                "state": new_state,
                "provider-id": record.get("provider-id"),
                "model-id": record.get("model-id"),
                "close-reason": reason,
                "turn-count": record.get("turn-count"),
            }, correlation_id=handle.correlation_id if handle else None)
        logger.info("gateway session closed", extra={"session-id": session_id, "close-reason": reason})
        return record if record is not None else {"session-id": session_id, "state": "closed"}

    async def _close_all(self, *, reason: str) -> None:
        for session_id in list(self._handles):
            handle = self._handles.get(session_id)
            if handle is None:
                continue
            try:
                await self._close(handle.project_root, session_id, reason=reason)
            except Exception:  # noqa: BLE001 — close every session regardless
                logger.warning("session close failed during close-all", extra={"session-id": session_id}, exc_info=True)

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
                            handle.project_root, session_id, "session.turn.silence-timeout",
                            state="active",
                            attributes={
                                "request-id": handle.current_request_id,
                                "silence-timeout-seconds": silence_cap,
                            },
                        )
                    except Exception:  # noqa: BLE001 — reaper must not die
                        logger.debug("failed to record stall timeline", exc_info=True)
                    # Closing the transport aborts the in-flight prompt; its
                    # exception path owns the durable failure + slot release.
                    await self._fail_session(handle, reason="turn-silence-timeout")
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
