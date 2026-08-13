from __future__ import annotations

import asyncio
from pathlib import Path

from acp.schema import TextContentBlock

from audiagentic.components.agents.protocols.acp import AcpAgent, UnsupportedAcpOperation


class FakeAgentsPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def open_agent_context(self, root, agent_id, title=None):
        self.calls.append(("open", agent_id))
        return {"context_id": "ctx_1", "state": "open"}

    def get_agent_context(self, root, context_id):
        self.calls.append(("get", context_id))
        return {"context_id": context_id, "state": "open"}

    def list_agent_contexts(self, root):
        return [{"context_id": "ctx_1", "state": "open"}]

    def close_agent_context(self, root, context_id):
        self.calls.append(("close", context_id))
        return {"context_id": context_id, "state": "closed"}

    def submit_agent_work(self, root, context_id, message, **kwargs):
        self.calls.append(("submit", message["text"]))
        return {"work_id": "work_1", "context_id": context_id, "state": "completed"}

    def get_agent_work(self, root, work_id):
        return {"work_id": work_id, "state": "completed"}

    def list_agent_work(self, root):
        return []

    def cancel_agent_work(self, root, work_id):
        self.calls.append(("cancel", work_id))
        return {"work_id": work_id, "state": "cancelled"}

    def read_agent_work_output(self, root, work_id):
        return {"work_id": work_id, "output": "done"}


def test_acp_projects_context_and_work_through_public_ports(tmp_path: Path) -> None:
    ports = FakeAgentsPort()
    adapter = AcpAgent(tmp_path, "agent-test", ports)

    async def scenario():
        created = await adapter.new_session(str(tmp_path))
        result = await adapter.prompt(
            created.sessionId,
            [TextContentBlock(type="text", text="hello")],
        )
        await adapter.close_session(created.sessionId)
        return created, result

    created, result = asyncio.run(scenario())
    assert created.sessionId == "ctx_1"
    assert result.stopReason == "end_turn"
    assert ("submit", "hello") in ports.calls
    assert ("close", "ctx_1") in ports.calls


def test_acp_rejects_client_owned_extensions(tmp_path: Path) -> None:
    adapter = AcpAgent(tmp_path, "agent-test", FakeAgentsPort())

    async def scenario():
        await adapter.new_session(str(tmp_path), mcp_servers=[object()])

    try:
        asyncio.run(scenario())
    except UnsupportedAcpOperation:
        pass
    else:
        raise AssertionError("client MCP injection must be rejected")
