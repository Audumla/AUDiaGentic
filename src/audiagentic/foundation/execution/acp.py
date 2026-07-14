"""Provider-neutral Agent Client Protocol transport.

Protocol framing and child lifecycle come from the official ACP SDK. This
module owns no provider selection, profiles, retries, queues, or persistence.

Implements the frozen neutral event and lifecycle contract per
docs/reference/AGENT_EXECUTION_TRANSPORTS.md §'Neutral event and lifecycle
contract — FROZEN'. Deviations require a plan review on MA18.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
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

# Bounded delivery defaults (overridable per call)
MAX_EVENTS = 10_000
MAX_PAYLOAD_BYTES = 64 * 1024  # 64 KiB
MAX_TOTAL_BYTES = 8 * 1024 * 1024  # 8 MiB

# Callback failure threshold before disabling
CALLBACK_FAILURE_LIMIT = 3

# Cancellation grace period (seconds) after SIGTERM before SIGKILL
CANCEL_GRACE_SECONDS = 5

# Canonical kind vocabulary (closed set; new kinds require MA18 review)
_KIND_VOCABULARY = frozenset({
    "assistant-message", "thought", "status", "usage",
    "tool-call", "file-change", "terminal-output", "plan-update",
    "permission-request", "error", "result",
})

# Mapping: raw ACP sessionUpdate values → canonical kind
_RAW_TO_CANONICAL = {
    "agent_message_chunk": "assistant-message",
    "thought": "thought",
    "status": "status",
    "usage": "usage",
    "tool_call": "tool-call",
    "file_change": "file-change",
    "terminal_output": "terminal-output",
    "plan_update": "plan-update",
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
    """Extract safe display text from canonical kind + payload."""
    if kind == "assistant-message":
        return payload.get("text")
    if kind == "thought":
        return payload.get("text")
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

    Permissions default-deny unless ``policy_fn`` grants access.  On cancel
    via ``cancel_signal``, the protocol-level cancel is attempted first,
    followed by bounded child termination (terminate, then kill after grace).
    Exactly one terminal ``result`` event is emitted regardless of race.
    """
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

    # Bounded delivery state
    events: list[AcpEvent] = []
    total_received = 0
    dropped = 0
    bytes_counted = 0
    callback_disabled_flag = False
    consecutive_callback_failures = 0

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def _emit_callback(event: AcpEvent) -> None:
        """Emit event to caller callback with failure isolation."""
        nonlocal consecutive_callback_failures, callback_disabled_flag
        if not on_event or callback_disabled_flag:
            return
        try:
            result = on_event(event)
            if result is not None:
                await result
            consecutive_callback_failures = 0
        except Exception:
            consecutive_callback_failures += 1
            if consecutive_callback_failures >= CALLBACK_FAILURE_LIMIT:
                callback_disabled_flag = True
                # Emit status event to record callback disable (self-referential)
                disable_event = AcpEvent(
                    sequence=len(events),
                    kind="status",
                    timestamp=_now(),
                    session_id=event.session_id,
                    text=f"on_event callback disabled after {CALLBACK_FAILURE_LIMIT} failures",
                    terminal=False,
                    error=None,
                    ext={},
                )
                events.append(disable_event)

    async def emit(session_id: str, raw_kind: str, payload: dict[str, Any]) -> None:
        """Emit an event with bounded delivery and normalization."""
        nonlocal total_received, dropped, bytes_counted

        total_received += 1
        canonical = _map_kind(raw_kind)
        text = _extract_text(canonical, payload)

        # Hard event cap: drop non-terminal events beyond limit
        if len(events) >= MAX_EVENTS and canonical != "result":
            dropped += 1
            return

        # Serialize ext for byte accounting
        ext = {"acp": {"raw_kind": raw_kind, "payload": payload}}
        ext_bytes = len(str(ext).encode("utf-8"))

        if bytes_counted + ext_bytes > MAX_TOTAL_BYTES and canonical != "result":
            # Over total byte budget — drop non-terminal payloads to header-only
            dropped += 1
            return

        _, ext_was_cut = _truncate_bytes(
            str(ext).encode("utf-8"), MAX_PAYLOAD_BYTES
        )
        if ext_was_cut:
            ext["_truncated"] = True  # type: ignore[literal-required]

        bytes_counted += len(str(ext).encode("utf-8"))

        event = AcpEvent(
            sequence=len(events),
            kind=canonical,
            timestamp=_now(),
            session_id=str(session_id),
            text=text,
            terminal=False,
            error=None,
            ext=ext,
        )
        events.append(event)
        await _emit_callback(event)

    async def emit_error(
        session_id: str, code: str, message: str, payload_excerpt: dict[str, Any] | None = None
    ) -> None:
        """Emit a non-terminal error-kind event (malformed update)."""
        event = AcpEvent(
            sequence=len(events),
            kind="error",
            timestamp=_now(),
            session_id=str(session_id),
            text=message,
            terminal=False,
            error={"code": code, "message": message},
            ext={"acp": {"raw_excerpt": payload_excerpt or {}}},
        )
        events.append(event)
        await _emit_callback(event)

    def emit_terminal(
        session_id: str,
        stop_reason: str | None,
        error: dict[str, str] | None = None,
    ) -> AcpEvent:
        """Emit the terminal result event. Always retained."""
        nonlocal total_received
        total_received += 1
        event = AcpEvent(
            sequence=len(events),
            kind="result",
            timestamp=_now(),
            session_id=str(session_id),
            text=None,
            terminal=True,
            error=error,
            ext={"acp": {"stop_reason": stop_reason}},
        )
        events.append(event)
        return event

    class GatewayClient(Client):
        async def request_permission(
            self, session_id, tool_call, options, **kwargs
        ) -> dict[str, Any]:
            """Default-deny unless policy_fn grants access."""
            tc_info = {
                "tool-call": _plain(tool_call),
                "options": [_plain(o) for o in options],
            }
            await emit(session_id, "permission-request", tc_info)

            if policy_fn is not None:
                result = policy_fn(str(session_id), _plain(tool_call))
                if isinstance(result, Awaitable):
                    result = await result
                return result

            return {"outcome": {"outcome": "cancelled"}}

        async def session_update(self, session_id, update, **kwargs) -> None:
            """Forward session updates with malformed-update normalization."""
            try:
                payload = _plain(update)
                await emit(session_id, str(payload.get("sessionUpdate", "update")), payload)
            except Exception as exc:
                # Malformed update: normalize to error event, continue
                await emit_error(
                    session_id,
                    ERR_MALFORMED_UPDATE,
                    f"Malformed ACP update: {type(exc).__name__}",
                    _plain(update),
                )

    session = None

    try:
        async with spawn_agent_process(
            GatewayClient(), launch.executable, *launch.args, env=dict(launch.environment) or None
        ) as (connection, _proc):
            await connection.initialize(protocol_version=PROTOCOL_VERSION)
            session = await connection.new_session(
                cwd=str(cwd.resolve()), mcp_servers=[]
            )

            # Cooperative cancellation check before prompt
            if cancel_signal is not None and cancel_signal.is_set():
                terminal = emit_terminal(str(session.session_id), "cancelled")
                return AcpResult(
                    session_id=str(session.session_id),
                    stop_reason="cancelled",
                    events=tuple(events),
                    total_events=total_received,
                    dropped_events=dropped,
                    bytes_buffered=bytes_counted,
                    terminal_event=terminal,
                    callback_disabled=callback_disabled_flag,
                )

            response = await connection.prompt(
                session_id=session.session_id,
                prompt=[text_block(prompt)],
            )
    except AudiaGenticError:
        raise
    except asyncio.CancelledError as exc:
        # Unexpected child exit due to task cancellation
        terminal = emit_terminal(
            str(session.session_id) if session else "unknown",
            "cancelled",
            error={"code": ERR_CHILD_EXIT, "message": "Agent process cancelled unexpectedly"},
        )
        raise AudiaGenticError(
            code=ERR_EXECUTION_FAILED,
            kind="execution",
            message="ACP agent execution failed",
            details={
                "executable": launch.executable,
                "error-type": type(exc).__name__,
            },
        ) from exc
    except Exception as exc:
        # Unexpected child exit: normalize to canonical error
        terminal = emit_terminal(
            str(session.session_id) if session else "unknown",
            None,
            error={"code": ERR_CHILD_EXIT, "message": type(exc).__name__},
        )
        raise AudiaGenticError(
            code=ERR_EXECUTION_FAILED,
            kind="execution",
            message="ACP agent execution failed",
            details={
                "executable": launch.executable,
                "error-type": type(exc).__name__,
            },
        ) from exc

    # Normal completion: emit terminal result event
    stop_reason = (
        str(response.stop_reason) if response.stop_reason is not None else None
    )
    terminal = emit_terminal(str(session.session_id), stop_reason)

    return AcpResult(
        session_id=str(session.session_id),
        stop_reason=stop_reason,
        events=tuple(events),
        total_events=total_received,
        dropped_events=dropped,
        bytes_buffered=bytes_counted,
        terminal_event=terminal,
        callback_disabled=callback_disabled_flag,
    )
