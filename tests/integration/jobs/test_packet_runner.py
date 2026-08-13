# ruff: noqa: E402, I001

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.components.agent_jobs.packet_runner import run_packet


def test_packet_runner_submits_canonical_work_when_context_is_provided(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner-work")
    try:
        calls: list[tuple[Path, str, dict, dict]] = []

        class Gateway:
            def submit_agent_work(self, root, context_id, message, **kwargs):
                calls.append((root, context_id, message, kwargs))
                return {
                    "work_id": "work_packet_1",
                    "context_id": context_id,
                    "state": "active",
                }

        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.client.get_gateway_client",
            lambda root: Gateway(),
        )

        result = run_packet(
            sandbox.repo,
            packet_id="pkt-work-001",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            context_id="ctx-packet-1",
            overrides={"stage-timeout-seconds": 30},
        )

        assert result["state"] == "active"
        assert len(calls) == 1
        root, context_id, message, kwargs = calls[0]
        assert root == sandbox.repo
        assert context_id == "ctx-packet-1"
        assert message["message_id"] == "packet:pkt-work-001"
        assert message["inputs"] == {
            "packet-id": "pkt-work-001",
            "project-id": "my-project",
            "provider-id": "local-openai",
            "workflow-profile": "lite",
            "stage-timeout-seconds": 30,
        }
        assert kwargs["work_id"]
        assert not (sandbox.repo / ".audiagentic" / "runtime" / "jobs").exists()
    finally:
        sandbox.cleanup()
