"""Thin ACP 0.11 adapter over the public Agents GatewayClient seam."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Protocol

from acp.schema import (
    AgentCapabilities,
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    ResumeSessionResponse,
    SessionInfo,
)

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error, make_error_factory

from .mapping import (
    UnsupportedAcpOperation,
    reject_client_extensions,
    text_from_prompt,
    validate_cwd,
)


class AgentsPort(Protocol):
    def open_agent_context(self, root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]: ...
    def get_agent_context(self, root: Path, context_id: str) -> dict[str, Any]: ...
    def list_agent_contexts(self, root: Path) -> list[dict[str, Any]]: ...
    def close_agent_context(self, root: Path, context_id: str) -> dict[str, Any]: ...
    def accept_agent_work_message(self, root: Path, context_id: str, message: dict[str, Any], *, protocol: str, work_id: str | None = None, exclusive: bool = False) -> dict[str, Any]: ...
    def wait_agent_work(self, root: Path, work_id: str, timeout_seconds: float | None = None) -> dict[str, Any]: ...
    def get_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def list_agent_work(self, root: Path) -> list[dict[str, Any]]: ...
    def cancel_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, root: Path, work_id: str) -> dict[str, Any]: ...


#: Work states that end a prompt; anything else keeps the prompt open (ACP has no "still working" reply).
_TERMINAL = frozenset({"completed", "failed", "cancelled", "rejected"})
#: One bounded wait per round; the prompt loops until the Work is terminal, so no wait ever returns early.
_WAIT_ROUND_SECONDS = 120.0
_MAX_OUTPUT_CHARS = 64_000


_error = make_error_factory("CON", "ACP", "acp")


class AcpAgent:
    """ACP implementation bound to one project and one configured Agent (SH62a).

    A prompt is a command the gateway accepts exactly once. ACP 0.11 carries no client retry identity, so
    each prompt gets a fresh owner-side message id: a transport retry is a new prompt, never a silent replay
    of one that may already have had an effect. At most one prompt per session is outstanding, decided from
    durable Work state (so it survives a reconnect), never from an in-memory map.
    """

    def __init__(self, project_root: Path, agent_id: str, ports: AgentsPort) -> None:
        self.project_root = project_root.resolve()
        self.agent_id = agent_id
        self.ports = ports
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def initialize(self, protocol_version: int, **_: Any) -> InitializeResponse:
        return InitializeResponse(
            protocolVersion=protocol_version,
            agentCapabilities=AgentCapabilities(loadSession=True),
            agentInfo=Implementation(name="audiagentic", version="0.1.0"),
        )

    async def new_session(self, cwd: str, additional_directories=None, mcp_servers=None, **_: Any) -> NewSessionResponse:
        validate_cwd(self.project_root, cwd)
        reject_client_extensions(mcp_servers, additional_directories)
        context = self.ports.open_agent_context(self.project_root, self.agent_id)
        return NewSessionResponse(sessionId=str(context["context_id"]))

    async def load_session(self, cwd: str, session_id: str, mcp_servers=None, additional_directories=None, **_: Any) -> LoadSessionResponse:
        validate_cwd(self.project_root, cwd)
        reject_client_extensions(mcp_servers, additional_directories)
        context = self.ports.get_agent_context(self.project_root, session_id)
        if context.get("state") != "open":
            raise ValueError("ACP can only load an OPEN Agent Context")
        return LoadSessionResponse()

    async def list_sessions(self, cwd: str | None = None, cursor: str | None = None, **_: Any) -> ListSessionsResponse:
        if cwd is not None:
            validate_cwd(self.project_root, cwd)
        contexts = self.ports.list_agent_contexts(self.project_root)
        return ListSessionsResponse(
            sessions=[SessionInfo(sessionId=str(item["context_id"]), cwd=str(self.project_root)) for item in contexts if item.get("state") == "open"],
        )

    def _outstanding(self, session_id: str) -> list[dict[str, Any]]:
        return [work for work in self.ports.list_agent_work(self.project_root)
                if work.get("context_id") == session_id and work.get("state") not in _TERMINAL]

    async def prompt(self, session_id: str, prompt: list[Any], **_: Any) -> PromptResponse:
        try:
            text = text_from_prompt(prompt)
        except ValueError as error:
            raise make_error(prefix="VAL", component="ACP", number=3, kind="acp",
                             message="An ACP prompt must contain text", details={"session": session_id}) from error
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:  # one adapter instance; the exclusive acceptance below is the cross-process guarantee
            try:
                accepted = await asyncio.to_thread(
                    self.ports.accept_agent_work_message, self.project_root, session_id,
                    {"message_id": f"acp:{uuid.uuid4().hex}", "text": text, "inputs": {}},
                    protocol="acp", exclusive=True,
                )
            except AudiaGenticError as error:
                if error.code == "CON-AGW-167":  # the Work owner refused: another prompt is outstanding
                    raise _error(1, "A prompt is already outstanding for this session", session=session_id) from error
                raise
        work = accepted
        while work.get("state") not in _TERMINAL:
            waited = await asyncio.to_thread(self.ports.wait_agent_work, self.project_root, accepted["work_id"], _WAIT_ROUND_SECONDS)
            work = waited["work"]
        state = work["state"]
        if state == "cancelled":
            return PromptResponse(stopReason="cancelled", _meta={"work": {"work_id": work["work_id"], "state": state}})
        if state != "completed":
            # ACP has no failure stop reason: report the real outcome instead of calling it end_turn.
            raise _error(2, "The prompt's Work did not complete", work_id=work["work_id"], state=state)
        output = await asyncio.to_thread(self.ports.read_agent_work_output, self.project_root, work["work_id"])
        return PromptResponse(stopReason="end_turn", _meta={
            "work": {"work_id": work["work_id"], "state": state}, "output": _bounded(output)})

    async def cancel(self, session_id: str, **_: Any) -> None:
        for work in await asyncio.to_thread(self._outstanding, session_id):
            await asyncio.to_thread(self.ports.cancel_agent_work, self.project_root, str(work["work_id"]))

    async def close_session(self, session_id: str, **_: Any) -> CloseSessionResponse:
        for work in self._outstanding(session_id):
            self.ports.cancel_agent_work(self.project_root, str(work["work_id"]))
        self.ports.close_agent_context(self.project_root, session_id)
        return CloseSessionResponse()

    async def resume_session(self, session_id: str, cwd: str, additional_directories=None, mcp_servers=None, **_: Any) -> ResumeSessionResponse:
        validate_cwd(self.project_root, cwd)
        reject_client_extensions(mcp_servers, additional_directories)
        await self.load_session(cwd, session_id)
        return ResumeSessionResponse()

    async def set_session_mode(self, *_: Any, **__: Any):
        raise UnsupportedAcpOperation("session modes are not backed by canonical Agents APIs")

    async def set_config_option(self, *_: Any, **__: Any):
        raise UnsupportedAcpOperation("session config options are not backed by canonical Agents APIs")

    async def authenticate(self, *_: Any, **__: Any):
        raise UnsupportedAcpOperation("ACP authentication is not owned by Agents")

    async def fork_session(self, *_: Any, **__: Any):
        raise UnsupportedAcpOperation("fork is not backed by canonical Context/Work")


def _bounded(output: Any) -> Any:
    """Keep a prompt response small: long text is cut, the full output stays in the gateway output store."""
    if isinstance(output, dict):
        text = output.get("text")
        if isinstance(text, str) and len(text) > _MAX_OUTPUT_CHARS:
            return {**output, "text": text[:_MAX_OUTPUT_CHARS], "truncated": True}
    return output
