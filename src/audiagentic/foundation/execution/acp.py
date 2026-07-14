"""Provider-neutral Agent Client Protocol transport.

Protocol framing and child lifecycle come from the official ACP SDK. This
module owns no provider selection, profiles, retries, queues, or persistence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


@dataclass(frozen=True)
class AcpLaunch:
    executable: str
    args: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AcpEvent:
    sequence: int
    kind: str
    session_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AcpResult:
    session_id: str
    stop_reason: str | None
    events: tuple[AcpEvent, ...]


EventCallback = Callable[[AcpEvent], Awaitable[None] | None]


def _plain(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {"value": str(value)}


async def run_acp_prompt(
    launch: AcpLaunch,
    *,
    cwd: Path,
    prompt: str,
    on_event: EventCallback | None = None,
) -> AcpResult:
    """Run one ACP session/turn and forward ordered neutral events.

    Permissions default-deny. Callers wanting approval must add a policy port;
    transport code never silently grants tool access.
    """
    try:
        from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
        from acp.interfaces import Client
    except ImportError as exc:
        raise AudiaGenticError(
            code="CFG-ACP-001",
            kind="execution",
            message="ACP transport dependency is not installed",
            details={"install-extra": "audiagentic[acp]"},
        ) from exc

    events: list[AcpEvent] = []

    async def emit(session_id: str, kind: str, payload: Any) -> None:
        event = AcpEvent(len(events), kind, str(session_id), _plain(payload))
        events.append(event)
        if on_event is not None:
            maybe_awaitable = on_event(event)
            if maybe_awaitable is not None:
                await maybe_awaitable

    class GatewayClient(Client):
        async def request_permission(self, session_id, tool_call, options, **kwargs):
            await emit(session_id, "permission-request", {
                "tool-call": _plain(tool_call),
                "options": [_plain(option) for option in options],
            })
            return {"outcome": {"outcome": "cancelled"}}

        async def session_update(self, session_id, update, **kwargs):
            payload = _plain(update)
            await emit(session_id, str(payload.get("sessionUpdate", "update")), payload)

    try:
        async with spawn_agent_process(
            GatewayClient(), launch.executable, *launch.args, env=dict(launch.environment) or None
        ) as (connection, _process):
            await connection.initialize(protocol_version=PROTOCOL_VERSION)
            session = await connection.new_session(cwd=str(cwd.resolve()), mcp_servers=[])
            response = await connection.prompt(
                session_id=session.session_id,
                prompt=[text_block(prompt)],
            )
    except AudiaGenticError:
        raise
    except Exception as exc:
        raise AudiaGenticError(
            code="EXT-ACP-001",
            kind="execution",
            message="ACP agent execution failed",
            details={"executable": launch.executable, "error-type": type(exc).__name__},
        ) from exc

    return AcpResult(
        session_id=str(session.session_id),
        stop_reason=str(response.stop_reason) if response.stop_reason is not None else None,
        events=tuple(events),
    )
