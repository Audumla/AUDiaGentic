"""Keep the agents MCP catalog and actual public tools in lockstep."""
from __future__ import annotations

import ast
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


def test_agents_mcp_catalog_matches_all_public_tool_exports() -> None:
    """Every decorated MCP tool must be cataloged exactly once on its surface."""
    config = load_yaml_file(_CONFIG)
    for server in config["mcp-servers"]:
        module = importlib.import_module(server["module"])
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        exported: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "mcp"
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            ):
                exported.add(node.name)
        declared = set(server["direct-tools"])
        assert exported == declared, (
            f"{server['name']} catalog drift: missing={sorted(exported - declared)}, "
            f"stale={sorted(declared - exported)}"
        )


def test_agents_mcp_tool_names_are_unique_across_surfaces() -> None:
    config = load_yaml_file(_CONFIG)
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for server in config["mcp-servers"]:
        for tool_name in server["direct-tools"]:
            previous = seen.setdefault(tool_name, server["name"])
            if previous != server["name"]:
                duplicates.append(f"{tool_name}: {previous}, {server['name']}")
    assert not duplicates, "Agents MCP tools must have one owning surface: " + ", ".join(duplicates)


def test_new_gateway_mcp_tools_are_provisioned_on_the_correct_surfaces() -> None:
    config = load_yaml_file(_CONFIG)
    servers = {server["name"]: set(server["direct-tools"]) for server in config["mcp-servers"]}

    assert {"agent_gateway_status", "agent_gateway_get_config"} <= servers[
        "ag-agents-admin"
    ]
    assert "agent_task_session_resume" in servers["ag-agents-gateway"]
