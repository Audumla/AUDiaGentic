"""Pinned MCP SDK metadata and per-tool output-channel contract."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from jsonschema import validate
from mcp.types import CallToolResult

from audiagentic.foundation.mcp import component_server


def _server(*, selected: frozenset[str] = frozenset(), descriptions=None, server_wide=False):
    server = component_server._AutoDescFastMCP(
        "fixture.module",
        "fixture",
        structured_output_only=server_wide,
        structured_output_tool_names=selected,
    )
    server._get_decl = lambda: SimpleNamespace(tool_descriptions=descriptions or {})
    return server


def _schema(server, name: str):
    return next(tool for tool in asyncio.run(server.list_tools()) if tool.name == name)


def test_rich_yaml_parameters_appear_in_tools_list_without_schema_override():
    server = _server(
        descriptions={
            "calculate": {
                "description": "Fixture metadata",
                "parameters": {
                    "count": "Requested count",
                    "enabled": {"description": "Whether to enable"},
                },
            }
        }
    )

    @server.tool()
    def calculate(count: int, enabled: bool = False) -> dict[str, int]:
        return {"count": count}

    published = _schema(server, "calculate")
    props = published.inputSchema["properties"]
    assert published.description == "Fixture metadata"
    assert props["count"]["description"] == "Requested count"
    assert props["enabled"]["description"] == "Whether to enable"
    assert props["count"]["type"] == "integer"
    assert props["enabled"]["default"] is False
    assert published.inputSchema["required"] == ["count"]
    assert inspect.signature(server._tool_manager.get_tool("calculate").fn) == inspect.signature(
        calculate
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"typo": "Unrecognized parameter"},
        {"count": {"description": "Incorrect override", "type": "string"}},
        {"count": {"default": 100}},
    ],
)
def test_bad_parameter_metadata_rejected_without_registering_tool(metadata):
    server = _server(descriptions={"calculate": {"description": "Fixture", "parameters": metadata}})
    with pytest.raises(ValueError):

        @server.tool()
        def calculate(count: int = 1) -> dict[str, int]:
            return {"count": count}

    assert server._tool_manager.get_tool("calculate") is None


def test_selected_structured_result_matches_advertised_schema_and_legacy_unchanged():
    server = _server(selected=frozenset({"selected"}))

    @server.tool()
    def selected(count: int = 4) -> dict[str, int]:
        return {"count": count}

    @server.tool()
    def legacy(count: int = 4) -> dict[str, int]:
        return {"count": count}

    selected_schema = _schema(server, "selected")
    legacy_schema = _schema(server, "legacy")
    assert selected_schema.inputSchema["properties"] == legacy_schema.inputSchema["properties"]
    assert selected_schema.outputSchema["required"] == ["result"]
    result = asyncio.run(server.call_tool("selected", {"count": 7}))
    assert isinstance(result, CallToolResult)
    assert result.content == []
    assert result.structuredContent == {"result": {"count": 7}}
    validate(result.structuredContent, selected_schema.outputSchema)

    old = asyncio.run(server.call_tool("legacy", {"count": 7}))
    assert isinstance(old, tuple)
    assert len(old) == 2
    assert old[1] == {"count": 7}
    assert old[0]
    assert legacy_schema.outputSchema != selected_schema.outputSchema
    assert inspect.signature(server._tool_manager.get_tool("selected").fn) == inspect.signature(
        selected
    )


def test_async_scalar_and_list_structured_schemas_match_results():
    server = _server(selected=frozenset({"async_value", "list_value"}))

    @server.tool()
    async def async_value(number: int) -> int:
        return number + 1

    @server.tool()
    def list_value(number: int) -> list[int]:
        return [number]

    for name, args, value in (
        ("async_value", {"number": 5}, 6),
        ("list_value", {"number": 5}, [5]),
    ):
        result = asyncio.run(server.call_tool(name, args))
        assert isinstance(result, CallToolResult)
        assert result.content == []
        assert result.structuredContent == {"result": value}
        validate(result.structuredContent, _schema(server, name).outputSchema)


def test_existing_server_wide_switch_still_selects_all_tools():
    server = _server(server_wide=True)

    @server.tool()
    def numeric(value: int) -> int:
        return value

    result = asyncio.run(server.call_tool("numeric", {"value": 9}))
    assert isinstance(result, CallToolResult)
    assert result.structuredContent == {"result": 9}
    validate(result.structuredContent, _schema(server, "numeric").outputSchema)


def test_explicit_call_tool_result_passthrough_and_errors():
    server = _server(selected=frozenset({"passthrough", "fails"}))

    @server.tool()
    def passthrough() -> CallToolResult:
        return CallToolResult(content=[], structuredContent={"already": True})

    @server.tool()
    def fails(value: int) -> dict[str, int]:
        raise ValueError("fixture error")

    returned = asyncio.run(server.call_tool("passthrough", {}))
    assert isinstance(returned, CallToolResult)
    assert returned.structuredContent == {"already": True}
    assert _schema(server, "passthrough").outputSchema is None
    with pytest.raises(Exception, match="fixture error"):
        asyncio.run(server.call_tool("fails", {"value": 1}))


def test_factory_forwards_selected_names_without_changing_default(monkeypatch):
    monkeypatch.setattr(component_server, "_resolve_mcp_server_name", lambda _: "fixture")
    server = component_server.mcp_server(
        "fixture.module", structured_output_tool_names=frozenset({"a"})
    )
    assert server._structured_output_tool_names == frozenset({"a"})
    assert server._structured_output_only is False
    default = component_server.mcp_server("fixture.module")
    assert default._structured_output_tool_names == frozenset()
