from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "tools" / "mcp" / "audiagentic-planning" / "audiagentic-planning_mcp.py"


def _run_raw_mcp_exchange(*messages: dict[str, object]) -> tuple[list[dict[str, object]], str]:
    payload = "\n".join(json.dumps(message) for message in messages) + "\n"
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=5,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return responses, proc.stderr


def test_raw_stdio_harness_initializes_and_lists_tools_and_resources() -> None:
    tool_responses, tool_stderr = _run_raw_mcp_exchange(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "raw-harness-test", "version": "0.1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    )
    resource_responses, resource_stderr = _run_raw_mcp_exchange(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "raw-harness-test", "version": "0.1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/list",
            "params": {},
        },
    )

    initialize = next(response for response in tool_responses if response["id"] == 1)
    assert initialize["result"]["serverInfo"]["name"] == "audiagentic-planning"
    assert initialize["result"]["protocolVersion"] == "2025-03-26"

    tools = next(response for response in tool_responses if response["id"] == 2)
    tool_names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "tm_new_request" in tool_names
    assert "tm_list" in tool_names
    assert "tm_verify_structure" in tool_names

    resources = next(response for response in resource_responses if response["id"] == 3)
    assert resources["result"]["resources"] == []

    assert "ListToolsRequest" in tool_stderr
    assert "ListResourcesRequest" in resource_stderr
