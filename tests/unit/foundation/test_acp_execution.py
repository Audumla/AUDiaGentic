from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.execution.acp import AcpLaunch, run_acp_prompt


def test_missing_sdk_has_canonical_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "acp", None)
    with pytest.raises(AudiaGenticError, match="CFG-ACP-001"):
        asyncio.run(run_acp_prompt(AcpLaunch("agent"), cwd=tmp_path, prompt="hello"))


def test_prompt_forwards_ordered_updates_and_denies_permission(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class Client:
        pass

    class Context:
        async def __aenter__(self):
            client = captured["client"]

            class Connection:
                async def initialize(self, **kwargs):
                    captured["initialize"] = kwargs

                async def new_session(self, **kwargs):
                    captured["new-session"] = kwargs
                    return SimpleNamespace(session_id="s1")

                async def prompt(self, **kwargs):
                    captured["prompt"] = kwargs
                    await client.session_update("s1", {"sessionUpdate": "agent_message_chunk", "text": "ok"})
                    outcome = await client.request_permission("s1", {"id": "t1"}, [{"optionId": "no"}])
                    assert outcome == {"outcome": {"outcome": "cancelled"}}
                    return SimpleNamespace(stop_reason="end_turn")

            return Connection(), object()

        async def __aexit__(self, *_args):
            return False

    def spawn(client, executable, *args, **kwargs):
        captured.update(client=client, executable=executable, args=args, spawn=kwargs)
        return Context()

    acp = types.ModuleType("acp")
    acp.PROTOCOL_VERSION = 1
    acp.spawn_agent_process = spawn
    acp.text_block = lambda text: {"type": "text", "text": text}
    interfaces = types.ModuleType("acp.interfaces")
    interfaces.Client = Client
    monkeypatch.setitem(sys.modules, "acp", acp)
    monkeypatch.setitem(sys.modules, "acp.interfaces", interfaces)

    seen = []
    result = asyncio.run(run_acp_prompt(
        AcpLaunch("agent", ("serve",), {"TOKEN": "redacted"}),
        cwd=tmp_path,
        prompt="hello",
        on_event=seen.append,
    ))

    assert result.session_id == "s1"
    assert result.stop_reason == "end_turn"
    assert [event.sequence for event in result.events] == [0, 1]
    assert [event.kind for event in seen] == ["agent_message_chunk", "permission-request"]
    assert captured["executable"] == "agent"
    assert captured["args"] == ("serve",)
    assert captured["new-session"] == {"cwd": str(tmp_path.resolve()), "mcp_servers": []}
    assert captured["prompt"]["prompt"] == [{"type": "text", "text": "hello"}]
