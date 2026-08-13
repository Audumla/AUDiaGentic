from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.protocols.a2a import A2aServerAdapter


class FakePorts:
    def list_agent_definitions(self, root):
        return [{"agent_id": "agent-a", "name": "A", "a2a": True, "publication": {"a2a": True}, "advertised_skills": ["review"]}]

    def get_agent_context(self, root, context_id):
        return {"context_id": context_id, "state": "open"}

    def open_agent_context(self, root, agent_id, title=None):
        return {"context_id": "ctx-a", "state": "open"}

    def submit_agent_work(self, root, context_id, message, **kwargs):
        return {"work_id": "work-a", "context_id": context_id, "state": "completed"}

    def get_agent_work(self, root, work_id):
        return {"work_id": work_id, "context_id": "ctx-a", "state": "completed"}

    def cancel_agent_work(self, root, work_id):
        return {"work_id": work_id, "context_id": "ctx-a", "state": "cancelled"}

    def read_agent_work_output(self, root, work_id):
        return {"text": "done"}


def test_a2a_uses_server_work_ids_and_published_cards(tmp_path: Path) -> None:
    adapter = A2aServerAdapter(tmp_path, "agent-a", FakePorts())
    assert adapter.agent_card()["skills"][0]["id"] == "review"
    result = adapter.message_send({"contextId": "ctx-a", "message": {"parts": [{"kind": "text", "text": "hello"}]}})
    assert result["id"] == "work-a"
    assert result["status"]["state"] == "completed"


def test_a2a_rejects_rich_parts(tmp_path: Path) -> None:
    adapter = A2aServerAdapter(tmp_path, "agent-a", FakePorts())
    with pytest.raises(ValueError, match="rich"):
        adapter.message_send({"contextId": "ctx-a", "message": {"parts": [{"kind": "file", "uri": "x"}]}})
