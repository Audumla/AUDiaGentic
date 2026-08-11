"""Manual live Gateway acceptance for gpt-auto.

Run from the repository root:

    python tests/gpt_auto/test_session_transport_live.py

This intentionally uses the same AgentTaskFactory/gateway path as the MCP
agent_task_submit tool. It sends a first prompt, follows up on the returned
Gateway session, verifies provider identity continuity, and closes the session.
"""

from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.components.agents.models.agent_task_api import AgentTaskFactory


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    factory = AgentTaskFactory(root)
    first = factory.submit(
        "gpt-auto-reviewer-agent",
        prompt_body="Review plan item AU01. Give two concise risks.",
        session_keep_alive=True,
        timeout_seconds=900,
        source="gpt-auto-live-test",
        metadata={"plan-item-id": "AU01"},
    )
    first_result = first.wait(930)
    if first_result.get("state") != "completed":
        print(json.dumps(first_result, default=str, indent=2))
        return 1
    session_id = first_result["session-id"]
    first_provider = first_result.get("provider-metadata") or {}

    second = factory.submit(
        "gpt-auto-reviewer-agent",
        prompt_body="Continue that review: which risk comes first? One sentence.",
        session_id=session_id,
        session_keep_alive=True,
        timeout_seconds=900,
        source="gpt-auto-live-test",
        metadata={"plan-item-id": "AU01"},
    )
    second_result = second.wait(930)
    second_provider = second_result.get("provider-metadata") or {}
    get_gateway_client().close_execution_session(root, session_id)

    ok = (
        second_result.get("state") == "completed"
        and second_result.get("session-id") == session_id
        and first_provider.get("provider-session-id") == second_provider.get("provider-session-id")
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "session-id": session_id,
                "provider-session-id-present": bool(second_provider.get("provider-session-id")),
                "first-output": first_result.get("output"),
                "second-output": second_result.get("output"),
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
