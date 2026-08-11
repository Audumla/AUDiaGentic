"""Keep the agents MCP catalog and actual public tools in lockstep."""
from __future__ import annotations

import importlib
from pathlib import Path

from audiagentic.foundation.io import load_yaml_file

_CONFIG = (
    Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components" / "agents.yaml"
)


def test_agents_mcp_catalog_declares_every_configured_direct_tool() -> None:
    config = load_yaml_file(_CONFIG)
    for server in config["mcp-servers"]:
        module = importlib.import_module(server["module"])
        descriptions = server.get("tool-descriptions", {})
        for tool_name in server["direct-tools"]:
            assert tool_name in descriptions, f"{server['name']} missing description for {tool_name}"
            assert callable(getattr(module, tool_name, None)), (
                f"{server['name']} declares missing callable {tool_name}"
            )


def test_new_gateway_mcp_tools_are_provisioned_on_the_correct_surfaces() -> None:
    config = load_yaml_file(_CONFIG)
    servers = {server["name"]: set(server["direct-tools"]) for server in config["mcp-servers"]}

    assert {"agent_gateway_create_operation", "agent_gateway_get_operation"} <= servers[
        "ag-agents-mgmt"
    ]
    assert "agent_task_session_resume" in servers["ag-agents-gateway"]
