"""Agent-facing MCP servers send small schemas and real instructions.

Every tool definition is paid for in model tokens on each session, so the
served schemas carry no generated titles or null defaults, the shared
``worktree`` argument stays a tiny string, and the YAML instructions actually
reach the client.
"""
from __future__ import annotations

import asyncio
import importlib
import json

import pytest

SERVERS = (
    "audiagentic.components.agents.mcp.gateway_mcp",
    "audiagentic.components.planning.planning_mcp",
    "audiagentic.components.ledger.ledger_mcp",
)
DESCRIPTION_LIMIT = 240
INSTRUCTION_LIMIT = 900


def _walk(node, *, in_properties=False):
    if isinstance(node, dict):
        for key, value in node.items():
            if not in_properties:
                yield key, value
            yield from _walk(value, in_properties=key == "properties" and not in_properties)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


@pytest.mark.parametrize("module", SERVERS)
def test_schemas_carry_no_titles_or_null_defaults(module):
    server = importlib.import_module(module).mcp
    for tool in asyncio.run(server.list_tools()):
        for schema in (tool.inputSchema, tool.outputSchema or {}):
            for key, value in _walk(schema):
                assert key != "title", f"{tool.name}: generated title left in schema"
                assert not (key == "default" and value is None), f"{tool.name}: null default left in schema"


@pytest.mark.parametrize("module", SERVERS)
def test_worktree_argument_is_a_plain_described_string(module):
    server = importlib.import_module(module).mcp
    for tool in asyncio.run(server.list_tools()):
        prop = tool.inputSchema["properties"]["worktree"]
        assert prop["type"] == "string" and len(json.dumps(prop)) < 120, tool.name
        assert "worktree" not in tool.inputSchema.get("required", [])


@pytest.mark.parametrize("module", SERVERS)
def test_descriptions_and_instructions_are_short_and_delivered(module):
    server = importlib.import_module(module).mcp
    assert 0 < len(server.instructions or "") <= INSTRUCTION_LIMIT
    for tool in asyncio.run(server.list_tools()):
        assert 0 < len(tool.description or "") <= DESCRIPTION_LIMIT, tool.name
