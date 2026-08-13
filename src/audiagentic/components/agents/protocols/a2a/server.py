"""A2A 1.0 semantic adapter over public Agents application ports."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from .agent_card import build_agent_card
from .mapping import text_message, work_status


class RemoteAgentTransport(Protocol):
    async def submit(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def status(self, endpoint: str, task_id: str) -> dict[str, Any]: ...
    async def output(self, endpoint: str, task_id: str) -> dict[str, Any]: ...
    async def cancel(self, endpoint: str, task_id: str) -> dict[str, Any]: ...


class A2aPorts(Protocol):
    def list_agent_definitions(self, root: Path) -> list[dict[str, Any]]: ...
    def get_agent_context(self, root: Path, context_id: str) -> dict[str, Any]: ...
    def open_agent_context(self, root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]: ...
    def submit_agent_work(self, root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def get_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def cancel_agent_work(self, root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, root: Path, work_id: str) -> dict[str, Any]: ...


class A2aServerAdapter:
    def __init__(self, project_root: Path, agent_id: str, ports: A2aPorts) -> None:
        self.project_root = project_root.resolve()
        self.agent_id = agent_id
        self.ports = ports

    def agent_card(self) -> dict[str, Any]:
        definition = next(item for item in self.ports.list_agent_definitions(self.project_root) if item["agent_id"] == self.agent_id)
        return build_agent_card(definition)

    def message_send(self, payload: dict[str, Any]) -> dict[str, Any]:
        context_id = payload.get("contextId")
        task_id = payload.get("taskId")
        if task_id:
            work = self.ports.get_agent_work(self.project_root, str(task_id))
            if context_id and work.get("context_id") != context_id:
                raise ValueError("taskId and contextId identify different objects")
            return self._task(work)
        if context_id:
            context = self.ports.get_agent_context(self.project_root, str(context_id))
            # A2A context IDs map directly to canonical Agent Contexts. A
            # closed context cannot accept another message; accepting it here
            # would create Work outside the Context lifecycle.
            if context.get("state") != "open":
                raise ValueError("A2A messages require an OPEN Agent Context")
        else:
            context_id = self.ports.open_agent_context(self.project_root, self.agent_id)["context_id"]
        text = text_message(payload["message"])
        message_id = _message_id(str(context_id), text)
        work_id = f"work_a2a_{hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:24]}"
        work = self.ports.submit_agent_work(
            self.project_root,
            str(context_id),
            {"message_id": message_id, "text": text, "inputs": {}, "source": "a2a"},
            work_id=work_id,
        )
        return self._task(work)

    def cancel(self, task_id: str) -> dict[str, Any]:
        return self._task(self.ports.cancel_agent_work(self.project_root, task_id))

    def _task(self, work: dict[str, Any]) -> dict[str, Any]:
        result = {"id": work["work_id"], "contextId": work["context_id"], "status": {"state": work_status(work)}}
        if work_status(work) == "completed":
            result["output"] = self.ports.read_agent_work_output(self.project_root, work["work_id"])
        return result


def _message_id(context_id: str, text: str) -> str:
    digest = hashlib.sha256(f"{context_id}\0{text}".encode()).hexdigest()[:24]
    return f"a2a:{context_id}:{digest}"
