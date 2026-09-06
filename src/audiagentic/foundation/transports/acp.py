"""Provider-neutral Agent Client Protocol transport.

Protocol framing and child lifecycle come from the official ACP SDK. This
module owns no provider selection, profiles, retries, queues, or persistence.

Implements the soft-frozen neutral event and lifecycle contract
referenced by docs/reference/AGENT_TRANSPORTS.md §'Neutral event and
lifecycle contract' (that doc was never actually created — RV512 asked
for it, it doesn't exist in the tree; treat this docstring as the
authoritative description until it is). "Soft-frozen" means: stable by
default, not immutable — thaw it via a plan review (recorded in the
plan item that motivates the change) rather than editing silently. See
AS68 for the recorded thaw of this contract: the fs/terminal Client
methods are implemented for real (path-confined file I/O and bounded
subprocess terminals), forwarding outcomes through the same
turn.emit(...) channel request_permission already uses. ``create_elicitation``
remains an intentional NotImplementedError — no evidenced consumer yet,
per the evidence-led scope rule in ARCHITECTURE_STANDARDS §3.

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
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    CorrelationQuality,
    ObservationSink,
    Scalar,
    SessionControlAction,
    SessionControlRequest,
    SessionControlResult,
    SessionFailureDisposition,
    SessionOpenResult,
    SessionPrompt,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)
from audiagentic.foundation.transports.session_binding import ProviderSessionRef

if TYPE_CHECKING:
    from acp import RequestPermissionResponse

logger = logging.getLogger(__name__)

# Registered error codes
ERR_SDK_MISSING = "CFG-ACP-001"
ERR_EXECUTION_FAILED = "EXT-ACP-001"
ERR_MALFORMED_UPDATE = "EXT-ACP-002"
ERR_CHILD_EXIT = "EXT-ACP-003"
ERR_SESSION_NOT_OPEN = "CON-ACP-001"
# AS49/AS10: resume requested but the agent's initialize response did not
# advertise agent_capabilities.load_session — never silently falls back to
# a fresh session (AS49 acceptance criteria: no fallback route for resume).
ERR_RESUME_UNSUPPORTED = "CON-ACP-004"
# AS68: real fs/terminal Client execution (thaw of AS28's control-only scope).
ERR_FS_ESCAPE = "CON-ACP-005"
ERR_UNKNOWN_TERMINAL = "CON-ACP-006"
ERR_FS_OPERATION_FAILED = "EXT-ACP-004"
ERR_TERMINAL_OPERATION_FAILED = "EXT-ACP-005"

# Default output cap for a terminal with no agent-supplied output_byte_limit
# (ACP's own MAX_TOTAL_BYTES-equivalent for a single terminal's lifetime).
_DEFAULT_TERMINAL_OUTPUT_LIMIT = 8 * 1024 * 1024  # 8 MiB


async def _terminate_and_reap_process(proc: Any, *, timeout: float) -> bool:
    """Boundedly terminate and reap one owned subprocess; never raise."""
    if getattr(proc, "returncode", None) is None:
        with suppress(Exception):
            proc.terminate()

    wait = getattr(proc, "wait", None)
    if wait is None:
        return getattr(proc, "returncode", None) is not None

    try:
        await asyncio.wait_for(wait(), timeout=timeout)
        return True
    except (Exception, asyncio.CancelledError):  # noqa: BLE001 - close never raises
        pass

    if getattr(proc, "returncode", None) is None:
        with suppress(Exception):
            proc.kill()

    try:
        await asyncio.wait_for(wait(), timeout=timeout)
        return True
    except (Exception, asyncio.CancelledError):  # noqa: BLE001 - close never raises
        logger.warning("owned ACP subprocess did not exit within the final reap deadline")
        return False

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
_KIND_VOCABULARY = frozenset(
    {
        "assistant-message",
        "thought",
        "status",
        "usage",
        "tool-call",
        "file-change",
        "terminal-output",
        "plan-update",
        "permission-request",
        "error",
        "result",
    }
)

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
class ProviderLaunch:
    """Normalized launch spec for any provider launch kind.

    A plain value shape — the executable, its argv, and extra environment —
    produced identically by one-shot execution, ACP, and interactive launch
    builders (recipe-driven or hand-written), then handed to the spawn
    strategy for that kind. Deliberately NOT a capability request (MA16): it
    carries no requester identity, mode, or policy, only the three fields a
    process launch needs.
    """

    executable: str
    args: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    # Standard ACP session configuration selected by the provider adapter.
    # These options are applied immediately after ``new_session`` and before
    # the session is exposed to a caller, so a provider cannot silently use
    # its default model instead of the admitted model.
    initial_config_options: tuple[tuple[str, str | bool], ...] = ()


# ``AcpLaunch`` is the historical name for this shape within the ACP subsystem
# (transport, session tests, AS28 boundary inventory). ACP launches ARE provider
# launches, so it stays as an alias rather than a second dataclass definition.
AcpLaunch = ProviderLaunch


class PreSpawnHook(Protocol):
    """Inversion-of-control seam: lets a caller do setup/teardown work keyed
    to the transport's own spawn lifecycle, without the transport exposing
    launch-environment details upward or needing to know what the caller
    does with them (AS41 — the Pi RPC tap needs the launch environment's
    tap address/authkey, which only exist pre-spawn, but AS28 forbids
    AcpLaunch/environment crossing into the gateway layer as a return
    value). The transport calls in; it never hands anything out.

    ``on_environment_ready``'s return value is opaque to the transport —
    passed back unchanged to ``on_close`` for symmetric teardown. Both
    methods are synchronous: implementations doing async work (e.g.
    starting a consumer task) should schedule it and return immediately,
    not block the spawn.
    """

    def on_environment_ready(self, environment: Mapping[str, str]) -> Any | None:
        """Called once the launch environment is finalized, before the
        child process spawns."""
        ...

    def on_close(self, hook_state: Any | None) -> None:
        """Called during transport close, symmetric with the spawn-time
        call. ``hook_state`` is whatever ``on_environment_ready`` returned
        (``None`` if it returned ``None`` or was never called)."""
        ...


class AuxiliaryObservationSource(Protocol):
    """A secondary producer of ``TransportObservation`` values correlated to
    the same session a transport's own native event stream already reports
    on. Generic and provider-blind by design — this module and the gateway
    never learn what backs a source (a tap, a side-channel log, anything).

    ``PreSpawnHook.on_environment_ready`` may optionally return an object
    implementing this protocol as (or inside) its ``hook_state``; the
    transport drains it during each turn, alongside its own native events,
    through the exact same ``sink`` callback the caller already receives —
    the caller sees one observation stream, never two.
    """

    async def poll(
        self,
        ag_session_id: str,
        turn_id: str | None,
    ) -> TransportObservation | None:
        """Return the next available observation, or ``None`` if none is
        currently pending. Must never block waiting for one — the transport
        polls this repeatedly for the duration of each turn.

        ``ag_session_id``/``turn_id`` are supplied by the caller (never
        known to the source itself, which is set up once at spawn — before
        any turn exists) so the source can stamp correct correlation onto
        each ``TransportObservation`` it constructs."""
        ...

    def close(self) -> None:
        """Release any resources. Called once, during transport close."""
        ...


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

        _, ext_was_cut = _truncate_bytes(str(ext).encode("utf-8"), MAX_PAYLOAD_BYTES)
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
        self,
        session_id: str,
        code: str,
        message: str,
        payload_excerpt: dict[str, Any] | None = None,
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


@dataclass
class _TerminalHandle:
    """AS68: one live `create_terminal`-spawned subprocess owned by this
    transport's ACP session client. `output`/`truncated`/`exit_status` are
    updated by the background drain task; `terminal_output`/
    `wait_for_terminal_exit` read them, never touch the process directly."""

    proc: asyncio.subprocess.Process
    output_byte_limit: int
    output: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    exit_status: Any = None  # acp.schema.TerminalExitStatus once known
    drain_task: asyncio.Task | None = None


def _terminal_exit_status(returncode: int | None) -> Any:
    """Build an ``acp.schema.TerminalExitStatus`` from a real subprocess
    returncode. ACP's schema forbids negative exit_code (``ge=0``); asyncio
    reports signal-terminated processes as a negative returncode on POSIX —
    translate that to the signal name instead, per the schema's own
    exit_code-XOR-signal shape."""
    from acp.schema import TerminalExitStatus

    if returncode is not None and returncode < 0:
        import signal as _signal

        try:
            sig_name = _signal.Signals(-returncode).name
        except ValueError:
            sig_name = str(-returncode)
        return TerminalExitStatus(exit_code=None, signal=sig_name)
    return TerminalExitStatus(exit_code=returncode, signal=None)


async def _drain_terminal(handle: _TerminalHandle) -> None:
    """Background task: continuously reads the terminal's merged
    stdout/stderr into ``handle.output`` (bounded by ``output_byte_limit``),
    then records the real exit status once the process ends. Never raises —
    a read failure just stops draining; the process is still reaped."""
    try:
        assert handle.proc.stdout is not None
        while True:
            chunk = await handle.proc.stdout.read(4096)
            if not chunk:
                break
            remaining = handle.output_byte_limit - len(handle.output)
            if remaining <= 0:
                handle.truncated = True
                continue
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
                handle.truncated = True
            handle.output.extend(chunk)
    except Exception:  # noqa: BLE001 — draining is best-effort
        pass
    finally:
        with suppress(Exception):
            returncode = await handle.proc.wait()
            handle.exit_status = _terminal_exit_status(returncode)


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
        pre_spawn_hook: PreSpawnHook | None = None,
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
        # AS49/AS10: agent_capabilities from the initialize response — None
        # before open()/open_resumed() has run. See supports_resume property.
        self._agent_capabilities: Any = None
        # AS41: inversion-of-control seam — see PreSpawnHook. hook_state is
        # whatever on_environment_ready returned, opaque to this class.
        self._pre_spawn_hook = pre_spawn_hook
        self._hook_state: Any = None
        self.dropped_between_turns = 0
        # AS68: real fs/terminal Client execution — live terminals created
        # by the agent via create_terminal, keyed by terminal_id.
        self._terminals: dict[str, _TerminalHandle] = {}

    def _confine_path(self, path: str) -> Path:
        """Resolve an agent-supplied path, rejecting anything outside this
        session's project root. ACP declares fs/terminal-cwd paths absolute,
        but the client is the trust boundary — never assume an agent (or a
        model driving it) stays inside the workspace it was given."""
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else (self._cwd / candidate)).resolve()
        root = self._cwd.resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise AudiaGenticError(
                code=ERR_FS_ESCAPE,
                kind="execution",
                message="ACP fs/terminal operation path escapes session project root",
                details={"path": path, "project-root": str(root)},
            )
        return resolved

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def child_pid(self) -> int | None:
        """OS pid of the spawned agent child, once open() has succeeded."""
        return getattr(self._proc, "pid", None)

    @property
    def hook_state(self) -> Any | None:
        """Whatever the pre-spawn hook's ``on_environment_ready`` returned.

        Opaque to this class — exposed only so a wrapper (e.g.
        ``AcpAgentSessionTransport``) can check whether it implements
        ``AuxiliaryObservationSource`` and drain it during turns.
        """
        return self._hook_state

    def is_alive(self) -> bool:
        """True while the transport is open and the child has not exited."""
        return (
            not self._closed
            and not self._dead
            and self._connection is not None
            and getattr(self._proc, "returncode", None) is None
        )

    @property
    def supports_resume(self) -> bool:
        """True once ``open()``/``open_resumed()`` has learned the agent
        advertises ``agent_capabilities.load_session`` in its initialize
        response. False before open, and false for agents that never
        advertise it (most ACP bridges today — see AS49 notes)."""
        return bool(getattr(self._agent_capabilities, "load_session", False))

    async def open(self) -> str:
        """Spawn the agent, initialize the protocol, create a NEW session.

        Returns the provider session id. Never leaks a child on failure —
        the exit stack is unwound before the error is raised.
        """
        stack, connection, proc = await self._spawn_and_initialize()
        try:
            session = await connection.new_session(cwd=str(self._cwd.resolve()), mcp_servers=[])
            for config_id, value in self._launch.initial_config_options:
                await connection.set_config_option(
                    config_id=config_id,
                    session_id=str(session.session_id),
                    value=value,
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
        self._finish_open(stack, connection, proc, str(session.session_id))
        assert self._session_id is not None
        return self._session_id

    async def open_resumed(self, provider_session_ref: str) -> str:
        """Spawn the agent, initialize the protocol, LOAD an existing session.

        AS49/AS10: never falls back to a fresh session. If the agent's
        initialize response does not advertise ``agent_capabilities.load_session``,
        raises :data:`ERR_RESUME_UNSUPPORTED` and tears the spawned child down —
        callers (AS49) must treat this as a hard resume failure, not a signal
        to silently open a new session instead.
        """
        stack, connection, proc = await self._spawn_and_initialize()
        if not self.supports_resume:
            with suppress(Exception, asyncio.CancelledError):
                await stack.aclose()
            self._dead = True
            raise AudiaGenticError(
                code=ERR_RESUME_UNSUPPORTED,
                kind="execution",
                message="ACP agent does not advertise agent_capabilities.load_session",
                details={
                    "executable": self._launch.executable,
                    "provider-session-ref": provider_session_ref,
                },
            )
        try:
            await connection.load_session(
                cwd=str(self._cwd.resolve()),
                session_id=provider_session_ref,
                mcp_servers=[],
            )
        except (Exception, asyncio.CancelledError) as exc:
            with suppress(Exception, asyncio.CancelledError):
                await stack.aclose()
            self._dead = True
            # RequestError's own message is always the generic JSON-RPC
            # string ("Invalid params", "Internal error", ...) -- the actual
            # reason a provider rejected the resume lives in .data, which is
            # otherwise silently lost here, forcing anyone debugging a resume
            # failure to go spelunking through the provider's own source.
            error_detail = str(exc)
            error_data = getattr(exc, "data", None)
            raise AudiaGenticError(
                code=ERR_EXECUTION_FAILED,
                kind="execution",
                message="ACP agent session/load failed",
                details={
                    "executable": self._launch.executable,
                    "provider-session-ref": provider_session_ref,
                    "error-type": type(exc).__name__,
                    "error-detail": error_detail,
                    "error-data": error_data,
                },
            ) from exc
        # LoadSessionResponse carries no session_id — the loaded session IS
        # the caller-supplied provider_session_ref (ACP session/load contract).
        self._finish_open(stack, connection, proc, provider_session_ref)
        assert self._session_id is not None
        return self._session_id

    async def _spawn_and_initialize(self) -> tuple[AsyncExitStack, Any, Any]:
        """Spawn the agent child and run the ACP initialize handshake.

        Shared by open() (session/new) and open_resumed() (session/load) —
        capability negotiation happens here, before either caller decides
        which session-creation method to call. Never leaks a child on
        failure; caller owns closing the returned stack on any later error.
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
            ) -> RequestPermissionResponse:
                """Default-deny unless policy_fn grants access."""
                from acp import RequestPermissionResponse

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
                    return RequestPermissionResponse.model_validate(result)

                return RequestPermissionResponse.model_validate(
                    {"outcome": {"outcome": "cancelled"}}
                )

            async def session_update(self, session_id, update, **kwargs) -> None:
                """Forward session updates with malformed-update normalization."""
                turn = transport._current_turn
                if turn is None:
                    transport.dropped_between_turns += 1
                    return
                try:
                    payload = _plain(update)
                    await turn.emit(
                        session_id, str(payload.get("sessionUpdate", "update")), payload
                    )
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

            # AS68 (2026-07-30): these were originally hard NotImplementedError
            # stubs on the theory that AS28's scope was "control/observation
            # only." That theory doesn't hold — in ACP the client IS the
            # execution backend for fs/terminal; the agent has no filesystem
            # or shell of its own. Refusing these meant no tool-using prompt
            # could ever complete: the agent would send the request and block
            # waiting for a response that never came, until it gave up and
            # tore the session down (observed directly via a real Docker e2e
            # run: a tool-invoking prompt produced a clean child-process EOF,
            # not a hang). Follows request_permission's own pattern just
            # above: perform the real operation, confine it to the session's
            # project root (_confine_path), then turn.emit(...) the result
            # through the same sink every other event uses. There is no
            # separate "observation" mechanism — forwarding real execution
            # IS the observation. Terminals are tracked in self._terminals
            # (a dict on the outer transport) and force-killed in close() if
            # the agent never calls release_terminal.
            async def write_text_file(self, session_id, path, content, **kwargs):
                from acp import WriteTextFileResponse

                turn = transport._current_turn
                try:
                    target = transport._confine_path(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                except AudiaGenticError:
                    raise
                except Exception as exc:
                    if turn is not None:
                        await turn.emit_error(
                            session_id,
                            ERR_FS_OPERATION_FAILED,
                            f"write_text_file failed: {type(exc).__name__}",
                            {"path": path},
                        )
                    raise AudiaGenticError(
                        code=ERR_FS_OPERATION_FAILED,
                        kind="execution",
                        message="ACP write_text_file failed",
                        details={"path": path, "error-type": type(exc).__name__},
                    ) from exc
                if turn is not None:
                    await turn.emit(
                        session_id,
                        "file_change",
                        {
                            "path": str(target),
                            "action": "write",
                            "bytes": len(content.encode("utf-8")),
                        },
                    )
                return WriteTextFileResponse()

            async def read_text_file(self, session_id, path, line=None, limit=None, **kwargs):
                from acp import ReadTextFileResponse

                turn = transport._current_turn
                try:
                    target = transport._confine_path(path)
                    text = target.read_text(encoding="utf-8")
                    if line is not None or limit is not None:
                        lines = text.splitlines(keepends=True)
                        start = max((line or 1) - 1, 0)
                        end = start + limit if limit is not None else None
                        text = "".join(lines[start:end])
                except AudiaGenticError:
                    raise
                except Exception as exc:
                    if turn is not None:
                        await turn.emit_error(
                            session_id,
                            ERR_FS_OPERATION_FAILED,
                            f"read_text_file failed: {type(exc).__name__}",
                            {"path": path},
                        )
                    raise AudiaGenticError(
                        code=ERR_FS_OPERATION_FAILED,
                        kind="execution",
                        message="ACP read_text_file failed",
                        details={"path": path, "error-type": type(exc).__name__},
                    ) from exc
                if turn is not None:
                    await turn.emit(
                        session_id,
                        "file_change",
                        {"path": str(target), "action": "read", "bytes": len(text.encode("utf-8"))},
                    )
                return ReadTextFileResponse(content=text)

            async def create_terminal(
                self,
                session_id,
                command,
                args=None,
                env=None,
                cwd=None,
                output_byte_limit=None,
                **kwargs,
            ):
                from acp import CreateTerminalResponse

                turn = transport._current_turn
                terminal_id = f"term-{uuid.uuid4().hex[:12]}"
                try:
                    term_cwd = transport._confine_path(cwd) if cwd else transport._cwd.resolve()
                    env_map = os.environ.copy()
                    for item in env or ():
                        name = getattr(item, "name", None)
                        value = getattr(item, "value", None)
                        if isinstance(item, dict):
                            name, value = item.get("name"), item.get("value")
                        if name is not None:
                            env_map[str(name)] = "" if value is None else str(value)
                    proc = await asyncio.create_subprocess_exec(
                        command,
                        *(args or ()),
                        cwd=str(term_cwd),
                        env=env_map,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    # Adopt the terminal process into a kill-on-close Job Object
                    # (Windows) so it cannot outlive this shim even if hard-killed.
                    # Bridge solution until async spawn_supervised exists.
                    try:
                        from audiagentic.foundation.system.supervised_process import (
                            adopt_pid_into_kill_job,
                        )

                        adopt_pid_into_kill_job(proc.pid)
                    except Exception:  # noqa: BLE001 — best effort, degrade gracefully
                        pass
                except AudiaGenticError:
                    raise
                except Exception as exc:
                    if turn is not None:
                        await turn.emit_error(
                            session_id,
                            ERR_TERMINAL_OPERATION_FAILED,
                            f"create_terminal failed: {type(exc).__name__}",
                            {"command": command},
                        )
                    raise AudiaGenticError(
                        code=ERR_TERMINAL_OPERATION_FAILED,
                        kind="execution",
                        message="ACP create_terminal failed",
                        details={"command": command, "error-type": type(exc).__name__},
                    ) from exc
                handle = _TerminalHandle(
                    proc=proc,
                    output_byte_limit=output_byte_limit or _DEFAULT_TERMINAL_OUTPUT_LIMIT,
                )
                handle.drain_task = asyncio.ensure_future(_drain_terminal(handle))
                transport._terminals[terminal_id] = handle
                if turn is not None:
                    await turn.emit(
                        session_id,
                        "terminal_output",
                        {"terminal_id": terminal_id, "status": "started", "command": command},
                    )
                return CreateTerminalResponse(terminal_id=terminal_id)

            async def terminal_output(self, session_id, terminal_id, **kwargs):
                from acp import TerminalOutputResponse

                handle = transport._terminals.get(terminal_id)
                if handle is None:
                    raise AudiaGenticError(
                        code=ERR_UNKNOWN_TERMINAL,
                        kind="execution",
                        message="Unknown ACP terminal id",
                        details={"terminal-id": terminal_id},
                    )
                return TerminalOutputResponse(
                    output=bytes(handle.output).decode("utf-8", errors="replace"),
                    truncated=handle.truncated,
                    exit_status=handle.exit_status,
                )

            async def release_terminal(self, session_id, terminal_id, **kwargs):
                handle = transport._terminals.pop(terminal_id, None)
                if handle is None:
                    return None
                if handle.drain_task is not None:
                    handle.drain_task.cancel()
                    with suppress(Exception, asyncio.CancelledError):
                        await handle.drain_task
                if getattr(handle.proc, "returncode", None) is None:
                    with suppress(Exception):
                        handle.proc.terminate()
                return None

            async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
                from acp import WaitForTerminalExitResponse

                handle = transport._terminals.get(terminal_id)
                if handle is None:
                    raise AudiaGenticError(
                        code=ERR_UNKNOWN_TERMINAL,
                        kind="execution",
                        message="Unknown ACP terminal id",
                        details={"terminal-id": terminal_id},
                    )
                if handle.drain_task is not None:
                    with suppress(Exception, asyncio.CancelledError):
                        await handle.drain_task
                status = handle.exit_status
                if status is None:
                    status = _terminal_exit_status(await handle.proc.wait())
                    handle.exit_status = status
                turn = transport._current_turn
                if turn is not None:
                    await turn.emit(
                        session_id,
                        "terminal_output",
                        {
                            "terminal_id": terminal_id,
                            "status": "exited",
                            "exit_code": status.exit_code,
                            "signal": status.signal,
                        },
                    )
                return WaitForTerminalExitResponse(exit_code=status.exit_code, signal=status.signal)

            async def kill_terminal(self, session_id, terminal_id, **kwargs):
                handle = transport._terminals.get(terminal_id)
                if handle is None:
                    return None
                if getattr(handle.proc, "returncode", None) is None:
                    with suppress(Exception):
                        handle.proc.kill()
                return None

            async def create_elicitation(self, message, mode, **kwargs):
                raise NotImplementedError(
                    "AcpAgentSessionTransport's session client does not support create_elicitation"
                )

            async def complete_elicitation(self, elicitation_id, **kwargs) -> None:
                return None

            async def ext_method(self, method, params) -> dict[str, Any]:
                return {}

            async def ext_notification(self, method, params) -> None:
                return None

            def on_connect(self, conn) -> None:
                return None

        # AS41: pre-spawn hook, called with the finalized launch environment
        # right before the child spawns — the only point this environment
        # (which may carry e.g. a tap address/authkey) is available. Never
        # raises: hook setup failure must not block opening the session.
        if self._pre_spawn_hook is not None:
            try:
                self._hook_state = self._pre_spawn_hook.on_environment_ready(
                    self._launch.environment
                )
            except Exception:  # noqa: BLE001 — hook setup is best-effort
                import logging

                logging.getLogger(__name__).warning(
                    "pre-spawn hook on_environment_ready failed", exc_info=True
                )
                self._hook_state = None

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
            init_response = await connection.initialize(protocol_version=PROTOCOL_VERSION)
            self._agent_capabilities = getattr(init_response, "agent_capabilities", None)
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
        return stack, connection, proc

    def _finish_open(
        self, stack: AsyncExitStack, connection: Any, proc: Any, session_id: str
    ) -> None:
        """Common tail of open()/open_resumed(): adopt state once a session id is known."""
        self._stack = stack
        self._connection = connection
        self._proc = proc
        self._session_id = session_id
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
                        error={
                            "code": ERR_CHILD_EXIT,
                            "message": "Agent process cancelled unexpectedly",
                        },
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

        stop_reason = str(response.stop_reason) if response.stop_reason is not None else None
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

        # AS68: any terminals the agent created but never released must not
        # outlive this transport — cancel their drain tasks and kill the
        # subprocess directly (release_terminal's polite path was never
        # called by the agent, so this is the only remaining guarantee).
        terminal_handles = list(self._terminals.values())
        for handle in terminal_handles:
            if handle.drain_task is not None:
                handle.drain_task.cancel()
        if terminal_handles:
            await asyncio.gather(
                *(
                    _terminate_and_reap_process(
                        handle.proc,
                        timeout=CANCEL_GRACE_SECONDS,
                    )
                    for handle in terminal_handles
                ),
                return_exceptions=True,
            )
        self._terminals.clear()

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
            aclose_task.add_done_callback(lambda task: task.cancelled() or task.exception())
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait({aclose_task}, timeout=CANCEL_GRACE_SECONDS)

        if proc is not None:
            await _terminate_and_reap_process(proc, timeout=CANCEL_GRACE_SECONDS)

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

        # AS41: symmetric pre-spawn-hook teardown. Never raises.
        if self._pre_spawn_hook is not None:
            try:
                self._pre_spawn_hook.on_close(self._hook_state)
            except Exception:  # noqa: BLE001 — hook teardown is best-effort
                import logging

                logging.getLogger(__name__).warning("pre-spawn hook on_close failed", exc_info=True)
            self._hook_state = None


# ---------------------------------------------------------------------------
# AcpAgentSessionTransport  (AS28 slice 2 — private provider-adapter wrapper)
# ---------------------------------------------------------------------------

# Mapping from ACP canonical event kind → TransportObservationKind.
# Unknown kinds fall through to TRANSPORT_UNKNOWN with no attributes.
_ACP_KIND_TO_TRANSPORT: dict[str, TransportObservationKind] = {
    "assistant-message": TransportObservationKind.ACTIVITY,
    "thought": TransportObservationKind.ACTIVITY,
    "status": TransportObservationKind.ACTIVITY,
    "usage": TransportObservationKind.ACTIVITY,
    "result": TransportObservationKind.TERMINAL,
    "error": TransportObservationKind.TRANSPORT_ERROR,
}


def _map_acp_event_to_observation(
    acp_event: AcpEvent,
    ag_session_id: str,
    turn_id: str | None,
) -> TransportObservation:
    """Map a raw AcpEvent to a bounded TransportObservation.

    Unknown ACP kinds produce TRANSPORT_UNKNOWN with no attributes —
    no raw kind name or payload leaks into the neutral contract.
    """
    acp_kind = acp_event.kind

    # --- Known: tool-call with status extraction ---
    if acp_kind == "tool-call":
        acp_ext = acp_event.ext.get("acp", {})
        status = str(acp_ext.get("status", ""))
        tool_call_id = acp_ext.get("tool_call_id")

        if status in ("pending", "started", "in_progress"):
            return TransportObservation(
                ag_session_id=ag_session_id,
                turn_id=turn_id,
                sequence=acp_event.sequence,
                kind=TransportObservationKind.TOOL_REQUESTED,
                observed_at=acp_event.timestamp,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={
                    "tool_call_id": tool_call_id,
                    "tool_status": status,
                },
            )
        elif status in ("completed", "finished", "failed", "cancelled"):
            return TransportObservation(
                ag_session_id=ag_session_id,
                turn_id=turn_id,
                sequence=acp_event.sequence,
                kind=TransportObservationKind.TOOL_FINISHED,
                observed_at=acp_event.timestamp,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={
                    "tool_call_id": tool_call_id,
                    "tool_status": status,
                },
            )
        else:
            # No status — unknown tool-call variant; drop to TRANSPORT_UNKNOWN
            return TransportObservation(
                ag_session_id=ag_session_id,
                turn_id=turn_id,
                sequence=acp_event.sequence,
                kind=TransportObservationKind.TRANSPORT_UNKNOWN,
                observed_at=acp_event.timestamp,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )

    # --- Known: permission-request ---
    if acp_kind == "permission-request":
        acp_ext = acp_event.ext.get("acp", {})
        tool_call_id = acp_ext.get("tool_call_id")
        return TransportObservation(
            ag_session_id=ag_session_id,
            turn_id=turn_id,
            sequence=acp_event.sequence,
            kind=TransportObservationKind.PERMISSION_REQUESTED,
            observed_at=acp_event.timestamp,
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={"tool_call_id": tool_call_id},
        )

    # --- Known: mapped kinds ---
    transport_kind = _ACP_KIND_TO_TRANSPORT.get(acp_kind)
    if transport_kind is not None:
        attrs: dict[str, Scalar] = {}

        if transport_kind == TransportObservationKind.TERMINAL:
            # Extract stop_reason from AcpEvent.error or ext
            stop_reason: str | None = None
            if acp_event.error is not None:
                stop_reason = acp_event.error.get("code")
            acp_ext = acp_event.ext.get("acp", {})
            ext_stop = acp_ext.get("stop_reason")
            if ext_stop is not None:
                stop_reason = str(ext_stop)
            error_code: str | None = None
            if acp_event.error is not None and acp_event.error.get("code"):
                error_code = acp_event.error["code"]
            if error_code:
                attrs["error_code"] = error_code
            if stop_reason:
                attrs["stop_reason"] = stop_reason
        elif transport_kind == TransportObservationKind.TRANSPORT_ERROR:
            if acp_event.error is not None:
                err_code = acp_event.error.get("code", "")
                if err_code:
                    attrs["error_code"] = err_code
                reason = acp_event.error.get("message") or acp_event.text or ""
                if reason:
                    attrs["reason"] = reason
            else:
                attrs["reason"] = acp_event.text or ""
        elif transport_kind == TransportObservationKind.ACTIVITY:
            # Labels are bounded evidence, never provider text/reasoning.
            if acp_event.text:
                attrs["model_activity"] = (
                    "thinking" if acp_kind == "thought" else "response-progress"
                )

        return TransportObservation(
            ag_session_id=ag_session_id,
            turn_id=turn_id,
            sequence=acp_event.sequence,
            kind=transport_kind,
            observed_at=acp_event.timestamp,
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes=attrs,
        )

    # --- Unknown: TRANSPORT_UNKNOWN, no attributes, no raw kind leak ---
    return TransportObservation(
        ag_session_id=ag_session_id,
        turn_id=turn_id,
        sequence=acp_event.sequence,
        kind=TransportObservationKind.TRANSPORT_UNKNOWN,
        observed_at=acp_event.timestamp,
        correlation_quality=CorrelationQuality.REQUEST_SCOPED,
    )


class AcpAgentSessionTransport:
    """Private provider-adapter wrapper: ACP → neutral AgentSessionTransport.

    Maps raw ACP event frames to bounded ``TransportObservation`` values and
    exposes only proven control capabilities. Raw ACP session refs, extension
    payload, and native kind names never leave this wrapper.

    This class is intentionally **not** in the public foundation transport
    exports (it is importable from ``acp.py`` for provider adapters and
    foundation contract tests). It implements ``AgentSessionTransport``
    protocol without any ``components.*`` imports.

    Control semantics:
    - CANCEL_TURN → ACCEPTED when transport is alive; UNSUPPORTED otherwise.
    - INTERRUPT_TURN / STEER_TURN → UNSUPPORTED (no ACP protocol support).
    - RESPOND_PERMISSION → default-deny (delegated to AcpSessionTransport
      policy_fn; no versioned ACP proof of permission response).
    - CLOSE_SESSION → delegates idempotently to underlying close.

    Never infers terminal durable state from a control acknowledgement.
    """

    def __init__(
        self,
        launch: AcpLaunch,
        *,
        cwd: Path,
        ag_session_id: str,
        policy_fn: PolicyCallback | None = None,
        compact_events: bool = False,
        resume_provider_ref: str | None = None,
        pre_spawn_hook: PreSpawnHook | None = None,
    ) -> None:
        self._inner: AcpSessionTransport = AcpSessionTransport(
            launch,
            cwd=cwd,
            policy_fn=policy_fn,
            compact_events=compact_events,
            pre_spawn_hook=pre_spawn_hook,
        )
        self._configured_ag_session_id = ag_session_id
        self._ag_session_id: str | None = None
        self._closed = False
        # Per-turn cancel signal for CANCEL_TURN control.
        self._current_cancel: asyncio.Event | None = None
        self._turn_active = False
        # AS49/AS10: when set, open() resumes this exact provider session ref
        # via ACP session/load instead of opening a new session. The caller
        # (AS49's resume workflow) is responsible for having already verified
        # AS29's resolved surface declares resume-by-ref supported — this
        # class does not re-check capability, it only executes the protocol
        # call and surfaces ERR_RESUME_UNSUPPORTED if the live agent disagrees.
        self._resume_provider_ref = resume_provider_ref

    @property
    def ag_session_id(self) -> str | None:
        """Canonical AG session id, set after open()."""
        return self._ag_session_id

    async def open(self) -> SessionOpenResult:
        """Open the underlying ACP transport.

        Opens a NEW session, unless constructed with ``resume_provider_ref``
        (AS49), in which case it loads that exact existing session instead —
        never both, never a silent fallback between the two.

        Returns canonical AG session id.
        """
        if self._resume_provider_ref is not None:
            await self._inner.open_resumed(self._resume_provider_ref)
        else:
            await self._inner.open()
        provider_session_id = self._inner.session_id
        if provider_session_id is None:
            raise AudiaGenticError(
                code="CON-ACP-002",
                kind="execution",
                message="ACP transport opened without a session id",
            )
        self._ag_session_id = self._configured_ag_session_id
        # Surface the raw provider-native session id in metadata too (not just
        # as ag_session_id/provider_session_ref internally) so callers can see
        # and independently use the underlying harness's own session identity
        # -- e.g. to resume against it directly with the provider's own tools,
        # long after AUDiaGentic's own session record has been closed or
        # pruned, since the harness itself (pi, opencode, ...) keeps its own
        # session store independently of ours.
        return SessionOpenResult(
            ag_session_id=self._configured_ag_session_id,
            provider_session_ref=ProviderSessionRef(provider_session_id),
            metadata={"provider-session-id": provider_session_id},
        )

    async def prompt(
        self,
        request: SessionPrompt,
        sink: ObservationSink,
    ) -> SessionTurnResult:
        """Run one turn, mapping AcpEvent → TransportObservation via *sink*."""
        if self._ag_session_id is None:
            raise AudiaGenticError(
                code="CON-ACP-001",
                kind="execution",
                message="AcpAgentSessionTransport not opened",
            )

        ag_sid = self._ag_session_id
        turn_id = request.turn_id
        delivered_count = 0
        dropped_count = 0
        _final_summary_parts: list[str] = []
        # Keep bounded provenance for a provider-side cancellation.  A tool
        # failure can make an ACP agent return ``stop_reason=cancelled`` even
        # though no gateway cancel was requested; without this distinction
        # the gateway reports a misleading clean cancellation and loses the
        # useful assistant text already emitted before the failed tool call.
        _failed_tool_call_ids: list[str] = []
        _cancelled_by_signal = False

        # Build the neutral observation sink that maps AcpEvent → TransportObservation.
        # Track whether model has started to emit ACTIVITY on first assistant-message,
        # then IN_PROGRESS for subsequent ones — this allows the projector to fire
        # TURN_MODEL_STARTED once, then repeated TURN_MODEL_IN_PROGRESS events.
        _model_started = False

        async def _wrapped_sink(acp_event: AcpEvent) -> None:
            nonlocal delivered_count, _model_started
            if acp_event.kind == "tool-call":
                acp_ext = acp_event.ext.get("acp", {})
                if str(acp_ext.get("status", "")) == "failed":
                    tool_call_id = acp_ext.get("tool_call_id")
                    if tool_call_id is not None and len(_failed_tool_call_ids) < 8:
                        _failed_tool_call_ids.append(str(tool_call_id))
            # The final response is an output concern, not an observation
            # delivery concern.  Preserve assistant text before projecting or
            # forwarding the event so a consumer-side mapping/sink failure
            # cannot silently turn a successful provider reply into an empty
            # terminal result.
            if acp_event.kind == "assistant-message" and acp_event.text:
                _final_summary_parts.append(acp_event.text)
            if acp_event.kind in {"assistant-message", "thought"} and not acp_event.text:
                return
            try:
                obs = _map_acp_event_to_observation(acp_event, ag_sid, turn_id)
                # Map subsequent assistant-messages to IN_PROGRESS after first ACTIVITY
                if acp_event.kind == "assistant-message":
                    if not _model_started:
                        _model_started = True
                    else:
                        from audiagentic.foundation.transports.agent_session import (
                            TransportObservation,
                            TransportObservationKind,
                        )

                        obs = TransportObservation(
                            ag_session_id=ag_sid,
                            turn_id=turn_id,
                            sequence=obs.sequence,
                            kind=TransportObservationKind.IN_PROGRESS,
                            observed_at=obs.observed_at,
                            correlation_quality=obs.correlation_quality,
                            attributes={"model_activity": "response-progress"} if acp_event.text else {},
                        )
                result = sink(obs)
                if asyncio.iscoroutine(result):
                    await result
                delivered_count += 1
            except Exception:
                # Sink callback exception isolation: never let a single
                # observation delivery failure kill the turn.
                pass

        # AS41: drain an AuxiliaryObservationSource (if the pre-spawn hook's
        # state implements one) for the duration of this turn only, feeding
        # its observations through the SAME sink — the caller never learns
        # a second source exists. Duck-typed (no @runtime_checkable
        # requirement on callers implementing the Protocol).
        aux_source = getattr(self._inner, "hook_state", None)
        _drain_task: asyncio.Task | None = None
        if aux_source is not None and hasattr(aux_source, "poll"):

            async def _drain_auxiliary_source() -> None:
                nonlocal delivered_count
                while True:
                    try:
                        obs = await aux_source.poll(ag_sid, turn_id)
                    except Exception:
                        # Source failure degrades richness only — never the turn.
                        return
                    if obs is None:
                        await asyncio.sleep(0.02)
                        continue
                    try:
                        result = sink(obs)
                        if asyncio.iscoroutine(result):
                            await result
                        delivered_count += 1
                    except Exception:
                        pass

            _drain_task = asyncio.ensure_future(_drain_auxiliary_source())

        self._current_cancel = asyncio.Event()
        self._turn_active = True
        try:
            acp_result = await self._inner.prompt(
                request.body,
                on_event=_wrapped_sink,
                cancel_signal=self._current_cancel if request.cancel_token is not None else None,
            )
            stop_reason = acp_result.stop_reason
            _cancelled_by_signal = self._current_cancel.is_set()
            # Count dropped ACP events (from FIFO eviction / budgeting).
            dropped_count = acp_result.dropped_events
        except AudiaGenticError:
            raise
        except Exception as exc:
            raise AudiaGenticError(
                code="EXT-ACP-001",
                kind="execution",
                message=f"ACP prompt execution failed: {type(exc).__name__}",
            ) from exc
        finally:
            self._turn_active = False
            self._current_cancel = None
            if _drain_task is not None:
                _drain_task.cancel()
                with suppress(asyncio.CancelledError):
                    await _drain_task

        return SessionTurnResult(
            turn_id=turn_id,
            stop_reason=stop_reason,
            observations_delivered=delivered_count,
            dropped_observations=dropped_count,
            error_code=(
                "EXT-ACP-TOOL-001"
                if stop_reason == "cancelled" and _failed_tool_call_ids
                else None
            ),
            final_summary="".join(_final_summary_parts) or None,
            metadata={
                "cancelled-by-signal": _cancelled_by_signal,
                "failed-tool-call-count": len(_failed_tool_call_ids),
                "failed-tool-call-ids": tuple(_failed_tool_call_ids),
            },
        )

    async def control(
        self,
        request: SessionControlRequest,
    ) -> SessionControlResult:
        """Canonical control with bounded disposition. No native escape hatch."""
        action = request.action

        if action == SessionControlAction.CANCEL_TURN:
            if not self.is_alive():
                return SessionControlResult(
                    disposition=ControlDisposition.UNSUPPORTED,
                )
            # Set the cancel signal for the current turn.
            # The ACP protocol will race against it in _inner.prompt().
            if self._current_cancel is not None:
                self._current_cancel.set()
            else:
                # No active turn — create a new one; next prompt() will see
                # it already set and return "cancelled" immediately.
                self._current_cancel = asyncio.Event()
                self._current_cancel.set()
            return SessionControlResult(
                disposition=ControlDisposition.ACCEPTED,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )

        if action in (SessionControlAction.INTERRUPT_TURN, SessionControlAction.STEER_TURN):
            # ACP protocol has no interrupt/steer support.
            return SessionControlResult(
                disposition=ControlDisposition.UNSUPPORTED,
                correlation_quality=CorrelationQuality.UNCERTAIN,
            )

        if action == SessionControlAction.RESPOND_PERMISSION:
            # Default-deny: ACP permission response requires versioned proof
            # that the protocol actually accepted it. Without that, deny.
            return SessionControlResult(
                disposition=ControlDisposition.UNSUPPORTED,
                correlation_quality=CorrelationQuality.UNCERTAIN,
            )

        if action == SessionControlAction.CLOSE_SESSION:
            await self.close()
            return SessionControlResult(
                disposition=ControlDisposition.ACCEPTED,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )

        # Should not be reachable (closed enum), but default-deny.
        return SessionControlResult(
            disposition=ControlDisposition.UNSUPPORTED,
        )

    async def close(self) -> None:
        """Shut the session down. Idempotent; never raises."""
        self._closed = True
        await self._inner.close()

    def is_alive(self) -> bool:
        """True while transport is open and child has not exited."""
        return not self._closed and self._inner.is_alive()

    def turn_failure_disposition(self) -> SessionFailureDisposition:
        """ACP has no provider-local recovery after a failed turn."""
        return SessionFailureDisposition.TERMINATE


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
        return await transport.prompt(prompt, on_event=on_event, cancel_signal=cancel_signal)
    finally:
        await transport.close()
