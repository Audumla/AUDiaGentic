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

from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports import AcpLaunch, AcpResult, AcpSessionTransport

logger = logging.getLogger(__name__)

# Gateway defaults — overridable per session at open time (config over code:
# dispatch resolves per-profile params session-idle-timeout-seconds /
# session-max-lifetime-seconds before calling open_session).
DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS = 900.0  # 15 min without a turn
DEFAULT_SESSION_MAX_LIFETIME_SECONDS = 14_400.0  # 4 h; 0 disables the cap
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
        created_clock: float,
    ) -> None:
        self.session_id = session_id
        self.transport = transport
        self.project_root = project_root
        self.agent_profile_id = agent_profile_id
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_lifetime_seconds = max_lifetime_seconds
        self.created_clock = created_clock
        self.last_activity_clock = created_clock
        # Turns are strictly serialized per session; waiters queue FIFO on the
        # lock (RV513 — queue, don't reject). pending counts waiters only.
        self.turn_lock = asyncio.Lock()
        self.pending = 0

    def quiescent(self) -> bool:
        """True when no turn is running and none are queued."""
        return not self.turn_lock.locked() and self.pending == 0


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
        timeout_seconds: float | None = None,
    ) -> AcpResult:
        """Run one turn on a live session; refreshes its idle clock."""
        return self._call(
            self._prompt(project_root, session_id, prompt, request_id=request_id),
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
        except Exception:
            # Never leak a child because bookkeeping failed.
            await transport.close()
            raise
        session_store.record_session_timeline(
            project_root, session_id, "session.opened", state="active",
            attributes={
                "agent-profile-id": agent_profile_id,
                "provider-id": provider_id,
                "model-id": model_id,
                "idle-timeout-seconds": idle_timeout_seconds,
                "max-lifetime-seconds": max_lifetime_seconds,
            },
        )
        self._handles[session_id] = _SessionHandle(
            session_id=session_id,
            transport=transport,
            project_root=project_root,
            agent_profile_id=agent_profile_id,
            idle_timeout_seconds=idle_timeout_seconds,
            max_lifetime_seconds=max_lifetime_seconds,
            created_clock=self._clock(),
        )
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
                attributes={"request-id": request_id},
            )
            try:
                result = await handle.transport.prompt(prompt)
            except Exception:
                # Transport marks itself dead on turn failure; reflect it durably.
                await self._fail_session(handle, reason="failed")
                raise
            finally:
                handle.last_activity_clock = self._clock()
        finally:
            handle.turn_lock.release()
        if request_id is not None:
            session_store.record_session_turn(project_root, session_id, request_id)
        session_store.record_session_timeline(
            project_root, session_id, "session.turn.finished", state="active",
            attributes={"request-id": request_id, "stop-reason": result.stop_reason},
        )
        return result

    async def _fail_session(self, handle: _SessionHandle, *, reason: str) -> None:
        self._handles.pop(handle.session_id, None)
        await handle.transport.close()
        try:
            record = session_store.read_session_record(handle.project_root, handle.session_id)
            if record["state"] not in session_store.SESSION_TERMINAL_STATES:
                session_store.transition_session_record(
                    handle.project_root, handle.session_id, "failed",
                    updates={"close-reason": reason, "closed-at": now_iso_z()},
                )
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
            session_store.record_session_timeline(
                project_root, session_id, "session.closed", state=record["state"],
                attributes={"close-reason": reason},
            )
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
            if handle is None or not handle.quiescent():
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
