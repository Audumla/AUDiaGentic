"""Thin ACP 0.11 adapter over the public Agents GatewayClient seam."""
from __future__ import annotations

import hashlib
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
    def submit_agent_work(self, root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def get_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def list_agent_work(self, root: Path) -> list[dict[str, Any]]: ...
    def cancel_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, root: Path, work_id: str) -> dict[str, Any]: ...


class AcpAgent:
    """ACP implementation bound to one project and one configured Agent."""

    def __init__(self, project_root: Path, agent_id: str, ports: AgentsPort) -> None:
        self.project_root = project_root.resolve()
        self.agent_id = agent_id
        self.ports = ports
        self._active_work: dict[str, str] = {}

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

    async def prompt(self, session_id: str, prompt: list[Any], **_: Any) -> PromptResponse:
        text = text_from_prompt(prompt)
        # ACP retries must address the same canonical Work.  The adapter does
        # not own a retry counter or a second lifecycle; identity is derived
        # solely from the protocol session and message content.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        message_id = f"acp:{session_id}:{digest}"
        work_id = f"work_acp_{hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:24]}"
        work = self.ports.submit_agent_work(
            self.project_root,
            session_id,
            {"message_id": message_id, "text": text, "inputs": {}, "source": "acp"},
            work_id=work_id,
        )
        work_id = str(work["work_id"])
        self._active_work[session_id] = work_id
        output = self.ports.read_agent_work_output(self.project_root, work_id)
        self._active_work.pop(session_id, None)
        return PromptResponse(stopReason="cancelled" if work.get("state") == "cancelled" else "end_turn", _meta={"work": work, "output": output})

    async def cancel(self, session_id: str, **_: Any) -> None:
        work_id = self._active_work.get(session_id)
        if work_id:
            self.ports.cancel_agent_work(self.project_root, work_id)

    async def close_session(self, session_id: str, **_: Any) -> CloseSessionResponse:
        for work in self.ports.list_agent_work(self.project_root):
            if work.get("context_id") == session_id and work.get("state") not in {"completed", "failed", "cancelled"}:
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
