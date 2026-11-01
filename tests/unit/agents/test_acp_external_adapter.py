"""SH62a: the ACP adapter over the gateway Work ports (one accepted command per prompt, durable outstanding check)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from acp import RequestError
from acp.schema import TextContentBlock

from audiagentic.components.agents.protocols.acp import AcpAgent
from audiagentic.foundation.contracts.errors import AudiaGenticError


class FakeAgentsPort:
    """In-memory Work ports; ``rounds`` waits report ``active`` before the Work reaches ``final``."""

    def __init__(self, *, final: str = "completed", rounds: int = 1) -> None:
        self.calls: list[tuple] = []
        self.works: dict[str, dict] = {}
        self.final = final
        self.rounds = rounds
        self.waits = 0
        self.output = {"text": "done"}

    def open_agent_context(self, root, agent_id, title=None):
        self.calls.append(("open", agent_id))
        return {"context_id": "ctx_1", "state": "open"}

    def get_agent_context(self, root, context_id):
        return {"context_id": context_id, "state": "open"}

    def list_agent_contexts(self, root):
        return [{"context_id": "ctx_1", "state": "open"}]

    def close_agent_context(self, root, context_id):
        self.calls.append(("close", context_id))
        return {"context_id": context_id, "state": "closed"}

    def accept_agent_work_message(self, root, context_id, message, *, protocol, work_id=None, exclusive=False):
        self.calls.append(("accept", message["text"], message["message_id"], protocol, work_id))
        if exclusive and any(w["context_id"] == context_id and w["state"] not in {"completed", "failed", "cancelled", "rejected"} for w in self.works.values()):
            raise AudiaGenticError("CON-AGW-167", "constraint", "outstanding")
        wid = f"work_{len(self.works) + 1}"
        self.works[wid] = {"work_id": wid, "context_id": context_id, "state": "active"}
        return dict(self.works[wid])

    def wait_agent_work(self, root, work_id, timeout_seconds=None):
        import time

        time.sleep(0.02)  # a real wait takes time; the test cancels while it is pending
        self.waits += 1
        if self.waits >= self.rounds and self.works[work_id]["state"] == "active":
            self.works[work_id]["state"] = self.final
        return {"work": dict(self.works[work_id]), "wait-outcome": "terminal"}

    def get_agent_work(self, root, work_id):
        return dict(self.works[work_id])

    def list_agent_work(self, root):
        return [dict(w) for w in self.works.values()]

    def cancel_agent_work(self, root, work_id):
        self.calls.append(("cancel", work_id))
        self.works[work_id]["state"] = "cancelled"
        return dict(self.works[work_id])

    def read_agent_work_output(self, root, work_id):
        return self.output


def _prompt(text="hello"):
    return [TextContentBlock(type="text", text=text)]


def test_acp_projects_context_and_work_through_public_ports(tmp_path: Path) -> None:
    ports = FakeAgentsPort()
    adapter = AcpAgent(tmp_path, "agent-test", ports)

    async def scenario():
        created = await adapter.new_session(str(tmp_path))
        result = await adapter.prompt(created.sessionId, _prompt())
        await adapter.close_session(created.sessionId)
        return created, result

    created, result = asyncio.run(scenario())
    assert created.sessionId == "ctx_1" and result.stopReason == "end_turn"
    assert result.field_meta["output"] == {"text": "done"}
    accept = next(call for call in ports.calls if call[0] == "accept")
    assert accept[1] == "hello" and accept[2].startswith("acp:") and accept[3] == "acp" and accept[4] is None
    assert ("close", "ctx_1") in ports.calls


def test_acp_rejects_client_owned_extensions(tmp_path: Path) -> None:
    adapter = AcpAgent(tmp_path, "agent-test", FakeAgentsPort())
    with pytest.raises(RequestError) as raised:
        asyncio.run(adapter.new_session(str(tmp_path), mcp_servers=[object()]))
    assert raised.value.code == -32602  # the method exists; the client asked for something it cannot have


def test_identical_prompts_are_distinct_commands_never_a_silent_replay(tmp_path: Path) -> None:
    ports = FakeAgentsPort()
    adapter = AcpAgent(tmp_path, "agent-test", ports)

    async def scenario():
        await adapter.prompt("ctx_1", _prompt("retry me"))
        await adapter.prompt("ctx_1", _prompt("retry me"))

    asyncio.run(scenario())
    accepts = [call for call in ports.calls if call[0] == "accept"]
    assert len(accepts) == 2 and accepts[0][2] != accepts[1][2]


def test_a_second_prompt_is_refused_while_one_is_outstanding_even_from_a_new_adapter(tmp_path: Path) -> None:
    ports = FakeAgentsPort()
    ports.works["work_9"] = {"work_id": "work_9", "context_id": "ctx_1", "state": "active"}
    reconnected = AcpAgent(tmp_path, "agent-test", ports)  # no in-memory state: the Work record decides
    with pytest.raises(RequestError) as raised:
        asyncio.run(reconnected.prompt("ctx_1", _prompt()))
    assert raised.value.code == -32600 and raised.value.data["code"] == "CON-ACP-001"
    ports.works["work_9"]["state"] = "completed"
    assert asyncio.run(reconnected.prompt("ctx_1", _prompt())).stopReason == "end_turn"


def test_the_prompt_stays_open_until_the_work_is_terminal(tmp_path: Path) -> None:
    ports = FakeAgentsPort(rounds=3)
    result = asyncio.run(AcpAgent(tmp_path, "agent-test", ports).prompt("ctx_1", _prompt()))
    assert ports.waits == 3 and result.stopReason == "end_turn"


@pytest.mark.parametrize("final", ["failed", "rejected"])
def test_a_failed_work_is_an_error_never_end_turn(tmp_path: Path, final: str) -> None:
    ports = FakeAgentsPort(final=final)
    with pytest.raises(RequestError) as raised:
        asyncio.run(AcpAgent(tmp_path, "agent-test", ports).prompt("ctx_1", _prompt()))
    assert raised.value.code == -32603 and raised.value.data["code"] == "CON-ACP-002"
    assert raised.value.data["state"] == final


def test_cancel_uses_durable_work_state_and_the_prompt_reports_cancelled(tmp_path: Path) -> None:
    ports = FakeAgentsPort(rounds=10_000)
    adapter = AcpAgent(tmp_path, "agent-test", ports)

    async def scenario():
        task = asyncio.create_task(adapter.prompt("ctx_1", _prompt()))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if ports.works:
                break
        # A different adapter instance (a reconnect) cancels through the Work record.
        await AcpAgent(tmp_path, "agent-test", ports).cancel("ctx_1")
        return await asyncio.wait_for(task, 5)

    assert asyncio.run(scenario()).stopReason == "cancelled"
    assert ("cancel", "work_1") in ports.calls


def test_long_output_is_bounded_in_the_response(tmp_path: Path) -> None:
    ports = FakeAgentsPort()
    ports.output = {"text": "x" * 200_000}
    result = asyncio.run(AcpAgent(tmp_path, "agent-test", ports).prompt("ctx_1", _prompt()))
    assert len(result.field_meta["output"]["text"]) == 64_000 and result.field_meta["output"]["truncated"] is True


# --- against the real Work owner (admission stubbed) ----------------------------------------------------

from .test_context_work import _seed  # noqa: E402


@pytest.mark.usefixtures("in_process_gateway")
def test_the_adapter_runs_against_the_real_work_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.agents.context.service import open_context
    from audiagentic.components.agents.gateway.client import get_gateway_client

    _seed(tmp_path)
    context = open_context(tmp_path, "a", "t")
    client = get_gateway_client(tmp_path)
    admitted: list[str] = []

    def admit(_root, **kwargs):
        admitted.append(kwargs["metadata"]["idempotency_key"])
        return {"request-id": f"req_{len(admitted)}", "state": "queued"}

    state = {"value": "running"}
    # The gateway application is a process-wide singleton: patch it with monkeypatch so it is restored.
    monkeypatch.setattr(client._application, "submit_execution_request", admit)

    def wait(root, rid, timeout=None):
        if state["value"] == "completed":
            return {"state": "completed"}
        return {"wait-outcome": "timeout", "status": {"state": "running"}}

    monkeypatch.setattr(client._application, "wait_execution_request", wait)

    adapter = AcpAgent(tmp_path, "a", client)

    async def scenario():
        task = asyncio.create_task(adapter.prompt(context.context_id, _prompt("hello")))
        await asyncio.sleep(0.3)
        with pytest.raises(RequestError) as raised:
            await adapter.prompt(context.context_id, _prompt("second"))
        assert raised.value.data["code"] == "CON-ACP-001"
        state["value"] = "completed"
        return await asyncio.wait_for(task, 10)

    result = asyncio.run(scenario())
    assert result.stopReason == "end_turn" and len(admitted) == 1


def test_a_prompt_without_text_is_a_registered_validation_error(tmp_path: Path) -> None:
    with pytest.raises(RequestError) as raised:
        asyncio.run(AcpAgent(tmp_path, "agent-test", FakeAgentsPort()).prompt("ctx_1", []))
    assert raised.value.code == -32602 and raised.value.data["code"] == "VAL-ACP-003"
