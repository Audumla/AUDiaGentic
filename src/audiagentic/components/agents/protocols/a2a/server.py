"""A2A 1.0 semantic adapter over the public Agents gateway ports (SH61a).

The adapter owns no identity, store or lifecycle. A message is identified by the caller's ``messageId`` (never
a hash of its text); the gateway builds the authenticated delivery identity, commits the command atomically
and admits it once, so replay, conflict, continuation and terminal-Work rules are the Work owner's. Wire
transport, SDK models and authentication are SH61b.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .agent_card import build_agent_card
from .mapping import is_terminal, output_text, text_message, work_status

#: Default wait for a blocking SendMessage; a timeout returns the real non-terminal task.
DEFAULT_WAIT_SECONDS = 120.0


class A2aPorts(Protocol):
    def list_agent_definitions(self, root: Path) -> list[dict[str, Any]]: ...
    def get_agent_context(self, root: Path, context_id: str) -> dict[str, Any]: ...
    def open_agent_context(self, root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]: ...
    def accept_agent_work_message(self, root: Path, context_id: str, message: dict[str, Any], *, protocol: str, work_id: str | None = None) -> dict[str, Any]: ...
    def wait_agent_work(self, root: Path, work_id: str, timeout_seconds: float | None = None) -> dict[str, Any]: ...
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

    def send_message(self, request: dict[str, Any]) -> dict[str, Any]:
        """``SendMessage``: accept one user message, continue or create the Task, return it (waiting by default)."""
        message = request.get("message")
        if not isinstance(message, dict):
            raise ValueError("SendMessage requires a message")
        message_id = message.get("messageId")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("A2A messages need a non-empty messageId")
        if message.get("role", "user") not in {"user", "ROLE_USER"}:
            raise ValueError("A2A SendMessage accepts user messages only")
        text = text_message(message)
        context_id, task_id = message.get("contextId"), message.get("taskId")
        if task_id:
            work = self.ports.get_agent_work(self.project_root, str(task_id))
            if context_id and work.get("context_id") != context_id:
                raise ValueError("taskId and contextId identify different objects")
            context_id = work["context_id"]
        if context_id:
            # A2A context ids map directly to canonical Agent Contexts; a closed one cannot take more Work.
            if self.ports.get_agent_context(self.project_root, str(context_id)).get("state") != "open":
                raise ValueError("A2A messages require an OPEN Agent Context")
        else:
            context_id = self.ports.open_agent_context(self.project_root, self.agent_id)["context_id"]
        accepted = self.ports.accept_agent_work_message(
            self.project_root, str(context_id),
            {"message_id": message_id, "text": text, "inputs": {}},
            protocol="a2a", work_id=str(task_id) if task_id else None,
        )
        configuration = request.get("configuration") or {}
        if configuration.get("returnImmediately"):
            return self._task(accepted)
        waited = self.ports.wait_agent_work(self.project_root, accepted["work_id"], DEFAULT_WAIT_SECONDS)
        return self._task(waited["work"])

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._task(self.ports.get_agent_work(self.project_root, task_id))

    def cancel(self, task_id: str) -> dict[str, Any]:
        work = self.ports.get_agent_work(self.project_root, task_id)
        state = work_status(work)
        if state == "canceled":
            return self._task(work)
        if is_terminal(state):
            raise ValueError(f"task {task_id!r} is already {state} and cannot be canceled")
        return self._task(self.ports.cancel_agent_work(self.project_root, task_id))

    def _task(self, work: dict[str, Any]) -> dict[str, Any]:
        state = work_status(work)
        task: dict[str, Any] = {"id": work["work_id"], "contextId": work["context_id"], "status": {"state": state}}
        if state == "completed":
            text = output_text(self.ports.read_agent_work_output(self.project_root, work["work_id"]))
            if text:
                task["artifacts"] = [{"artifactId": f"{work['work_id']}-output", "parts": [{"kind": "text", "text": text}]}]
        return task
