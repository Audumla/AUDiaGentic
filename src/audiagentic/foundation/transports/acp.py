"""Provider-neutral Agent Client Protocol transport.

Protocol framing and child lifecycle come from the official ACP SDK. This
module owns no provider selection, profiles, retries, queues, or persistence.

Implements the frozen neutral event and lifecycle contract per
docs/reference/AGENT_TRANSPORTS.md §'Neutral event and lifecycle
contract — FROZEN'. Deviations require a plan review on MA18.

Session lifecycle extension (RV512 on MA18, plan agent-sessions AS01):
``AcpSessionTransport`` keeps one child process and one protocol session
alive across multiple ``prompt()`` turns. The frozen event semantics are
unchanged — bounded delivery, callback isolation, default-deny permissions,
malformed-update normalization, and exactly-one-terminal-result all apply
per turn. ``run_acp_prompt`` remains the behaviour-identical one-shot path
(open → prompt → close). Process lifetime == session lifetime: there is no
resume-after-death here (deferred to AS10).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

# Registered error codes
ERR_SDK_MISSING = "CFG-ACP-001"
ERR_EXECUTION_FAILED = "EXT-ACP-001"
ERR_MALFORMED_UPDATE = "EXT-ACP-002"
ERR_CHILD_EXIT = "EXT-ACP-003"
ERR_SESSION_NOT_OPEN = "CON-ACP-001"

# Bounded delivery defaults (overridable per call)
MAX_EVENTS = 10_000
MAX_PAYLOAD_BYTES = 64 * 1024  # 64 KiB
MAX_TOTAL_BYTES = 8 * 1024 * 1024  # 8 MiB

# Callback failure threshold before disabling
CALLBACK_FAILURE_LIMIT = 3

# Cancellation grace period (seconds) after SIGTERM before SIGKILL
CANCEL_GRACE_SECONDS = 5

# Post-response drain: an agent writes its final session_update frames BEFORE
# the prompt response, but the SDK dispatches notifications as tasks that can
# still be pending when the prompt future resolves (AS06 real-subprocess
# finding). Yield to the loop, then wait one short beat, so already-received
# updates land in THIS turn's pipeline instead of being dropped between turns.
_TURN_DRAIN_YIELDS = 10
_TURN_DRAIN_SLEEP_SECONDS = 0.01

# When budgets force event drops, assistant-message TEXT is still preserved
# (bounded) in an overflow buffer — the final report is the one artifact a
# controller must never lose (MA29 live truncation, review on MA18).
MAX_OVERFLOW_TEXT_BYTES = 1024 * 1024  # 1 MiB

# Canonical kind vocabulary (closed set; new kinds require MA18 review)
_KIND_VOCABULARY = frozenset({
    "assistant-message", "thought", "status", "usage",
    "tool-call", "file-change", "terminal-output", "plan-update",
    "permission-request", "error", "result",
})

# Mapping: raw ACP sessionUpdate values → canonical kind.
# The left column must cover the REAL wire vocabulary (agent_thought_chunk,
# tool_call_update, plan, …), not just idealized names — RV679 on AS19 found
# turn-state detection silently depending on unmapped kinds leaking through
# raw. Legacy/raw-dict test spellings are retained as additional aliases.
_RAW_TO_CANONICAL = {
    "agent_message_chunk": "assistant-message",
    "agent_thought_chunk": "thought",
    "thought": "thought",
    "status": "status",
    "usage": "usage",
    "tool_call": "tool-call",
    "tool_call_update": "tool-call",
    "file_change": "file-change",
    "terminal_output": "terminal-output",
    "plan": "plan-update",
    "plan_update": "plan-update",
    "available_commands_update": "status",
    "current_mode_update": "status",
}


def _map_kind(raw: str) -> str:
    """Map raw ACP sessionUpdate to canonical kind. Unknown → raw value."""
    return _RAW_TO_CANONICAL.get(raw, raw)


@dataclass(frozen=True)
class AcpLaunch:
    executable: str
    args: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AcpEvent:
    sequence: int
    kind: str
    timestamp: str
    session_id: str
    text: str | None
    terminal: bool
    error: dict[str, str] | None
    ext: dict[str, Any]


@dataclass(frozen=True)
class AcpResult:
    session_id: str
    stop_reason: str | None
    events: tuple[AcpEvent, ...]
    total_events: int
    dropped_events: int
    bytes_buffered: int
    terminal_event: AcpEvent | None
    callback_disabled: bool
    # Assistant text carried by events the budgets dropped (bounded by
    # MAX_OVERFLOW_TEXT_BYTES). Consumers building output text must append
    # this after the retained events' text.
    overflow_text: str | None = None


EventCallback = Callable[[AcpEvent], Awaitable[None] | None]
PolicyCallback = Callable[
    [str, dict[str, Any]],  # session_id, tool_call_info
    Awaitable[dict[str, Any]] | dict[str, Any],
]


def _plain(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {"value": str(value)}


def _extract_text(kind: str, payload: dict[str, Any]) -> str | None:
    """Extract safe display text from canonical kind + payload.

    Handles both raw dict format (tests) and SDK model format (real agents):
    - Raw: {"text": "hello"}
    - SDK: {"content": {"type": "text", "text": "hello"}}
    """
    if kind in ("assistant-message", "thought"):
        text = payload.get("text")
        if text is not None:
            return text
        content = payload.get("content")
        if isinstance(content, dict):
            return content.get("text")
        return None
    if kind == "status":
        return payload.get("message")
    if kind == "error":
        err = payload.get("error")
        if isinstance(err, dict):
            return err.get("message")
    return None


def _truncate_bytes(data: bytes, limit: int) -> tuple[bytes, bool]:
    """Truncate data to byte limit. Returns (truncated_data, was_truncated)."""
    if len(data) <= limit:
        return data, False
    return data[:limit], True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TurnPipeline:
    """Bounded event delivery state for exactly one prompt turn.

    Owns the per-turn budgets from the frozen contract: MAX_EVENTS hard cap,
    MAX_TOTAL_BYTES budget, callback failure isolation, and the guarantee
    that the terminal ``result`` event is always retained.
    """

    def __init__(self, on_event: EventCallback | None, *, compact: bool = False) -> None:
        self.events: list[AcpEvent] = []
        self.total_received = 0
        self.dropped = 0
        self.bytes_counted = 0
        self.callback_disabled = False
        self._consecutive_callback_failures = 0
        self._on_event = on_event
        # Rolling FIFO retention: budgets EVICT OLDEST instead of dropping
        # newest — the recent window is what controllers and wedge detection
        # need, and the tail (final report) is the part that must survive.
        # Sequence is an arrival counter so it stays strictly increasing
        # across evictions; per-event byte sizes allow budget release.
        self._sequence = 0
        self._event_bytes: list[int] = []
        # Compact mode: never buffer raw update payloads in ext — only the
        # raw kind. For consumers that use text/kind/counts only (the gateway
        # session path), payload retention is pure memory cost and is what
        # exhausts the byte budget on long turns.
        self._compact = compact
        self._overflow_text: list[str] = []
        self._overflow_bytes = 0

    def _bank_overflow_text(self, canonical: str, text: str | None) -> None:
        """Preserve assistant text from an evicted/dropped event, bounded.

        With FIFO eviction the banked text is always OLDER than every
        retained event, so consumers assemble output as overflow + retained.
        """
        if canonical != "assistant-message" or not text:
            return
        encoded = len(text.encode("utf-8"))
        if self._overflow_bytes + encoded > MAX_OVERFLOW_TEXT_BYTES:
            return
        self._overflow_text.append(text)
        self._overflow_bytes += encoded

    def _evict_oldest(self) -> None:
        """Evict the oldest retained event, banking assistant text."""
        if not self.events:
            return
        evicted = self.events.pop(0)
        size = self._event_bytes.pop(0) if self._event_bytes else 0
        self.bytes_counted -= size
        self.dropped += 1
        self._bank_overflow_text(evicted.kind, evicted.text)

    def _retain(self, event: AcpEvent, size: int) -> None:
        self.events.append(event)
        self._event_bytes.append(size)
        self.bytes_counted += size

    async def _emit_callback(self, event: AcpEvent) -> None:
        """Emit event to caller callback with failure isolation."""
        if not self._on_event or self.callback_disabled:
            return
        try:
            result = self._on_event(event)
            if result is not None:
                await result
            self._consecutive_callback_failures = 0
        except Exception:
            self._consecutive_callback_failures += 1
            if self._consecutive_callback_failures >= CALLBACK_FAILURE_LIMIT:
                self.callback_disabled = True
                # Emit status event to record callback disable (self-referential)
                disable_event = AcpEvent(
                    sequence=self._sequence,
                    kind="status",
                    timestamp=_now(),
                    session_id=event.session_id,
                    text=f"on_event callback disabled after {CALLBACK_FAILURE_LIMIT} failures",
                    terminal=False,
                    error=None,
                    ext={},
                )
                self._sequence += 1
                self._retain(disable_event, 0)

    async def emit(self, session_id: str, raw_kind: str, payload: dict[str, Any]) -> None:
        """Emit an event with rolling bounded delivery and normalization.

        Budgets are enforced by EVICTING OLDEST retained events (banking
        their assistant text) so the buffer is always the most recent
        window — the tail carries the final report and the liveness signal.
        """
        self.total_received += 1
        canonical = _map_kind(raw_kind)
        text = _extract_text(canonical, payload)

        # Tool lifecycle identity survives even in compact mode: status and
        # toolCallId are what turn-state consumers key on, and dropping them
        # with the payload made tool events unobservable on the gateway path
        # (RV679 on AS19).
        acp_ext: dict[str, Any] = {"raw_kind": raw_kind}
        status = payload.get("status")
        if status is not None:
            acp_ext["status"] = str(status)
        tool_call_id = payload.get("toolCallId") or payload.get("tool_call_id")
        if tool_call_id is not None:
            acp_ext["tool_call_id"] = str(tool_call_id)
        if not self._compact:
            acp_ext["payload"] = payload
        ext: dict[str, Any] = {"acp": acp_ext}
        ext_bytes = len(str(ext).encode("utf-8"))

        _, ext_was_cut = _truncate_bytes(
            str(ext).encode("utf-8"), MAX_PAYLOAD_BYTES
        )
        if ext_was_cut:
            ext["_truncated"] = True  # type: ignore[literal-required]

        # Rolling FIFO: make room by event count, then by byte budget.
        while len(self.events) >= MAX_EVENTS:
            self._evict_oldest()
        while self.events and self.bytes_counted + ext_bytes > MAX_TOTAL_BYTES:
            self._evict_oldest()
        if ext_bytes > MAX_TOTAL_BYTES:
            # A single event larger than the whole budget: keep header-only.
            ext = {"acp": {"raw_kind": raw_kind}, "_truncated": True}
            ext_bytes = len(str(ext).encode("utf-8"))

        event = AcpEvent(
            sequence=self._sequence,
            kind=canonical,
            timestamp=_now(),
            session_id=str(session_id),
            text=text,
            terminal=False,
            error=None,
            ext=ext,
        )
        self._sequence += 1
        self._retain(event, ext_bytes)
        await self._emit_callback(event)

    async def emit_error(
        self, session_id: str, code: str, message: str, payload_excerpt: dict[str, Any] | None = None
    ) -> None:
        """Emit a non-terminal error-kind event (malformed update)."""
        while len(self.events) >= MAX_EVENTS:
            self._evict_oldest()
        ext = {"acp": {"raw_excerpt": payload_excerpt or {}}}
        event = AcpEvent(
            sequence=self._sequence,
            kind="error",
            timestamp=_now(),
            session_id=str(session_id),
            text=message,
            terminal=False,
            error={"code": code, "message": message},
            ext=ext,
        )
        self._sequence += 1
        self._retain(event, len(str(ext).encode("utf-8")))
        await self._emit_callback(event)

    async def emit_terminal(
        self,
        session_id: str,
        stop_reason: str | None,
        error: dict[str, str] | None = None,
    ) -> AcpEvent:
        """Emit the terminal result event. Always retained.

        Also delivered to the on_event callback — the terminal event is the
        one signal an observer needs to know the turn is over, and it was
        previously never emitted through the callback at all (RV679 on AS19).
        """
        self.total_received += 1
        while len(self.events) >= MAX_EVENTS:
            self._evict_oldest()
        ext = {"acp": {"stop_reason": stop_reason}}
        event = AcpEvent(
            sequence=self._sequence,
            kind="result",
            timestamp=_now(),
            session_id=str(session_id),
            text=None,
            terminal=True,
            error=error,
            ext=ext,
        )
        self._sequence += 1
        self._retain(event, len(str(ext).encode("utf-8")))
        await self._emit_callback(event)
        return event

    def build_result(
        self, session_id: str, stop_reason: str | None, terminal: AcpEvent | None
    ) -> AcpResult:
        return AcpResult(
            session_id=str(session_id),
            stop_reason=stop_reason,
            events=tuple(self.events),
            total_events=self.total_received,
            dropped_events=self.dropped,
            bytes_buffered=self.bytes_counted,
            terminal_event=terminal,
            callback_disabled=self.callback_disabled,
            overflow_text="".join(self._overflow_text) or None,
        )


class AcpSessionTransport:
    """One live ACP agent: one child process, one protocol session, many turns.

    Lifecycle: ``await open()`` (spawn → initialize → new_session), then any
    number of ``await prompt(...)`` calls — each a full frozen-contract turn
    with its own bounded event pipeline — then ``await close()`` (idempotent,
    bounded child termination). All methods must run on the same event loop.

    Session updates arriving while no turn is in flight are counted in
    ``dropped_between_turns`` and discarded — there is no cross-turn event
    buffer (a well-behaved ACP agent only emits during a prompt).

    A child that dies mid-turn marks the transport dead; further ``prompt()``
    calls raise CON-ACP-001. ``close()`` is always safe to call.
    """

    def __init__(
        self,
        launch: AcpLaunch,
        *,
        cwd: Path,
        policy_fn: PolicyCallback | None = None,
        compact_events: bool = False,
    ) -> None:
        self._launch = launch
        self._cwd = cwd
        self._policy_fn = policy_fn
        self._compact_events = compact_events
        self._stack: AsyncExitStack | None = None
        self._connection: Any = None
        self._proc: Any = None
        self._session_id: str | None = None
        self._text_block: Callable[[str], Any] | None = None
        self._current_turn: _TurnPipeline | None = None
        self._closed = False
        self._dead = False
        # AS17: foundation adopted child token (None before open or on refusal).
        self._adopted_child: object | None = None  # AdoptedChild | AdoptionRefusal | None
        self.dropped_between_turns = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def child_pid(self) -> int | None:
        """OS pid of the spawned agent child, once open() has succeeded."""
        return getattr(self._proc, "pid", None)

    def is_alive(self) -> bool:
        """True while the transport is open and the child has not exited."""
        return (
            not self._closed
            and not self._dead
            and self._connection is not None
            and getattr(self._proc, "returncode", None) is None
        )

    async def open(self) -> str:
        """Spawn the agent, initialize the protocol, create the session.

        Returns the provider session id. Never leaks a child on failure —
        the exit stack is unwound before the error is raised.
        """
        if self._closed or self._connection is not None:
            raise AudiaGenticError(
                code=ERR_SESSION_NOT_OPEN,
                kind="execution",
                message="ACP session transport already opened or closed",
                details={"session-id": self._session_id, "closed": self._closed},
            )
        try:
            from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
            from acp.interfaces import Client
        except ImportError as exc:
            raise AudiaGenticError(
                code=ERR_SDK_MISSING,
                kind="execution",
                message="ACP transport dependency is not installed",
                details={"install-extra": "audiagentic[acp]"},
            ) from exc
        self._text_block = text_block

        transport = self

        class _SessionClient(Client):
            async def request_permission(
                self, session_id, tool_call, options, **kwargs
            ) -> dict[str, Any]:
                """Default-deny unless policy_fn grants access."""
                turn = transport._current_turn
                if turn is not None:
                    tc_info = {
                        "tool-call": _plain(tool_call),
                        "options": [_plain(o) for o in options],
                    }
                    await turn.emit(session_id, "permission-request", tc_info)

                if transport._policy_fn is not None:
                    result = transport._policy_fn(str(session_id), _plain(tool_call))
                    if isinstance(result, Awaitable):
                        result = await result
                    return result

                return {"outcome": {"outcome": "cancelled"}}

            async def session_update(self, session_id, update, **kwargs) -> None:
                """Forward session updates with malformed-update normalization."""
                turn = transport._current_turn
                if turn is None:
                    transport.dropped_between_turns += 1
                    return
                try:
                    payload = _plain(update)
                    await turn.emit(session_id, str(payload.get("sessionUpdate", "update")), payload)
                except Exception as exc:
                    # Malformed update: normalize to error event, continue.
                    # Do not re-serialize the update — it may be the same object
                    # that failed serialization above.
                    await turn.emit_error(
                        session_id,
                        ERR_MALFORMED_UPDATE,
                        f"Malformed ACP update: {type(exc).__name__}",
                        None,
                    )

        stack = AsyncExitStack()
        try:
            connection, proc = await stack.enter_async_context(
                spawn_agent_process(
                    _SessionClient(),
                    self._launch.executable,
                    *self._launch.args,
                    env=dict(self._launch.environment) or None,
                )
            )
            await connection.initialize(protocol_version=PROTOCOL_VERSION)
            session = await connection.new_session(
                cwd=str(self._cwd.resolve()), mcp_servers=[]
            )
        except (Exception, asyncio.CancelledError) as exc:
            with suppress(Exception, asyncio.CancelledError):
                await stack.aclose()
            self._dead = True
            raise AudiaGenticError(
                code=ERR_EXECUTION_FAILED,
                kind="execution",
                message="ACP agent execution failed",
                details={
                    "executable": self._launch.executable,
                    "error-type": type(exc).__name__,
                },
            ) from exc

        self._stack = stack
        self._connection = connection
        self._proc = proc
        self._session_id = str(session.session_id)
        # AS17: adopt the SDK-spawned child into foundation ownership.
        # Captures ProcessEvidence + Windows kill-on-close Job Object
        # (hard-death guarantee). Best-effort: refusal leaves close() teardown
        # as the only guarantee — same as pre-existing behavior.
        if self.child_pid is not None:
            from audiagentic.foundation.system.adopted_process import adopt_child

            adopted = adopt_child(
                pid=self.child_pid,
                command=(self._launch.executable, *self._launch.args),
                owner_epoch="gateway-session",
                scope="session-child",
            )
            self._adopted_child = adopted
        return self._session_id

    async def prompt(
        self,
        prompt: str,
        *,
        on_event: EventCallback | None = None,
        cancel_signal: asyncio.Event | None = None,
    ) -> AcpResult:
        """Run one turn on the live session; full frozen-contract semantics.

        Exactly one terminal ``result`` event is produced per turn. A cancel
        signal already set skips the turn (stop_reason ``cancelled``). Any
        failure mid-turn marks the transport dead and raises EXT-ACP-001.
        """
        if not self.is_alive():
            raise AudiaGenticError(
                code=ERR_SESSION_NOT_OPEN,
                kind="execution",
                message="ACP session transport is not open",
                details={
                    "session-id": self._session_id,
                    "closed": self._closed,
                    "dead": self._dead,
                },
            )
        turn = _TurnPipeline(on_event, compact=self._compact_events)
        self._current_turn = turn
        cancelled_by_signal = False
        try:
            if cancel_signal is not None and cancel_signal.is_set():
                terminal = await turn.emit_terminal(str(self._session_id), "cancelled")
                return turn.build_result(str(self._session_id), "cancelled", terminal)

            response = None
            if cancel_signal is not None:
                # Race prompt against cancel signal — protocol-level cancel first.
                prompt_task = asyncio.ensure_future(
                    self._connection.prompt(
                        session_id=self._session_id,
                        prompt=[self._text_block(prompt)],  # type: ignore[misc]
                    )
                )
                cancel_task = asyncio.ensure_future(cancel_signal.wait())
                wait_done, wait_pending = await asyncio.wait(
                    {prompt_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if prompt_task in wait_done and not prompt_task.cancelled():
                    response = prompt_task.result()
                    cancel_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await cancel_task
                elif cancel_task in wait_done:
                    # Signal was set during prompt — protocol cancel, then abort.
                    with suppress(Exception):
                        cancel_fn = getattr(self._connection, "cancel", None)
                        if cancel_fn is not None:
                            await cancel_fn(self._session_id)
                    for t in wait_pending:
                        t.cancel()
                    cancelled_by_signal = True
                    with suppress(asyncio.CancelledError):
                        await prompt_task
            else:
                try:
                    response = await self._connection.prompt(
                        session_id=self._session_id,
                        prompt=[self._text_block(prompt)],  # type: ignore[misc]
                    )
                except asyncio.CancelledError as exc:
                    self._dead = True
                    await turn.emit_terminal(
                        str(self._session_id),
                        "cancelled",
                        error={"code": ERR_CHILD_EXIT, "message": "Agent process cancelled unexpectedly"},
                    )
                    raise AudiaGenticError(
                        code=ERR_EXECUTION_FAILED,
                        kind="execution",
                        message="ACP agent execution failed",
                        details={
                            "executable": self._launch.executable,
                            "error-type": type(exc).__name__,
                        },
                    ) from exc
                except Exception as exc:
                    # Unexpected child exit: normalize to canonical error
                    self._dead = True
                    await turn.emit_terminal(
                        str(self._session_id),
                        None,
                        error={"code": ERR_CHILD_EXIT, "message": type(exc).__name__},
                    )
                    raise AudiaGenticError(
                        code=ERR_EXECUTION_FAILED,
                        kind="execution",
                        message="ACP agent execution failed",
                        details={
                            "executable": self._launch.executable,
                            "error-type": type(exc).__name__,
                        },
                    ) from exc

            if cancelled_by_signal:
                terminal = await turn.emit_terminal(str(self._session_id), "cancelled")
                return turn.build_result(str(self._session_id), "cancelled", terminal)
            # Drain pending update dispatch before detaching the turn pipeline
            # (see _TURN_DRAIN_YIELDS). Failure paths skip this — the turn is
            # already lost and the transport is dead.
            for _ in range(_TURN_DRAIN_YIELDS):
                await asyncio.sleep(0)
            await asyncio.sleep(_TURN_DRAIN_SLEEP_SECONDS)
        finally:
            self._current_turn = None

        if response is None:
            raise AudiaGenticError(
                code=ERR_EXECUTION_FAILED,
                kind="execution",
                message="ACP agent execution failed — no prompt response",
                details={"executable": self._launch.executable},
            )

        stop_reason = (
            str(response.stop_reason) if response.stop_reason is not None else None
        )
        terminal = await turn.emit_terminal(str(self._session_id), stop_reason)
        return turn.build_result(str(self._session_id), stop_reason, terminal)

    async def close(self) -> None:
        """Shut the session down and guarantee the child is gone. Idempotent.

        Unwinds the SDK's process context (its own polite termination) under
        a CANCEL_GRACE_SECONDS bound, then force-terminates/kills anything
        still running. Never raises.
        """
        if self._closed:
            return
        self._closed = True
        self._current_turn = None
        stack, proc = self._stack, self._proc
        self._stack = None
        self._connection = None

        if stack is not None:
            # Never CANCEL stack.aclose(): cancelling the SDK's spawn context
            # mid-unwind corrupts its async generator ('aclose(): already
            # running' at loop shutdown — AS06 real-subprocess finding). Wait
            # bounded WITHOUT cancellation; on timeout let it finish in the
            # background and force-kill the child ourselves below.
            aclose_task = asyncio.ensure_future(stack.aclose())
            aclose_task.add_done_callback(
                lambda task: task.cancelled() or task.exception()
            )
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait({aclose_task}, timeout=CANCEL_GRACE_SECONDS)

        if proc is not None and getattr(proc, "returncode", None) is None:
            with suppress(Exception):
                proc.terminate()
            wait = getattr(proc, "wait", None)
            if wait is not None:
                try:
                    await asyncio.wait_for(wait(), timeout=CANCEL_GRACE_SECONDS)
                except (Exception, asyncio.CancelledError, asyncio.TimeoutError):
                    with suppress(Exception):
                        proc.kill()

        # AS17: close the foundation adopted-child token last.
        # Windows: closing the Job Object handle triggers kill-on-close for
        # any descendants that survived above. POSIX: no-op (no Job Object).
        if self._adopted_child is not None:
            from audiagentic.foundation.system.adopted_process import (
                AdoptedChild,
                close_kill_job,
            )

            if isinstance(self._adopted_child, AdoptedChild):
                close_kill_job(self._adopted_child)
            self._adopted_child = None


async def run_acp_prompt(
    launch: AcpLaunch,
    *,
    cwd: Path,
    prompt: str,
    on_event: EventCallback | None = None,
    cancel_signal: asyncio.Event | None = None,
    policy_fn: PolicyCallback | None = None,
) -> AcpResult:
    """Run one ACP session/turn and forward ordered neutral events.

    One-shot wrapper over AcpSessionTransport (open → prompt → close) —
    behaviour-identical to the original frozen-contract implementation.
    Permissions default-deny unless ``policy_fn`` grants access.  On cancel
    via ``cancel_signal``, the turn is skipped with stop_reason ``cancelled``.
    Exactly one terminal ``result`` event is emitted regardless of race.
    """
    transport = AcpSessionTransport(launch, cwd=cwd, policy_fn=policy_fn)
    try:
        await transport.open()
        return await transport.prompt(
            prompt, on_event=on_event, cancel_signal=cancel_signal
        )
    finally:
        await transport.close()
