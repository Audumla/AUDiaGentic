"""Tests for remote MCP server entry support (HM02)."""
from __future__ import annotations

from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)


def test_entry_is_remote():
    entry = McpServerEntry(name="test", url="http://example.com/mcp")
    assert entry.is_remote is True


def test_entry_is_stdio():
    entry = McpServerEntry(name="test", command="node", args=("--server",))
    assert entry.is_remote is False


def test_entry_default_is_stdio():
    entry = McpServerEntry(name="test")
    assert entry.is_remote is False


def test_json_roundtrip_remote(tmp_path):
    cfg_path = tmp_path / "test.mcp.json"
    entry = McpServerEntry(
        name="hindsight",
        url="http://10.10.100.10:8888/mcp",
        headers={"Authorization": "Bearer secret"},
        transport="http",
    )
    write_mcp_json(cfg_path, {"hindsight": entry})

    read_entries = read_mcp_json(cfg_path)
    read_entry = read_entries["hindsight"]
    assert read_entry.is_remote is True
    assert read_entry.url == "http://10.10.100.10:8888/mcp"
    assert read_entry.headers["Authorization"] == "Bearer secret"
    assert read_entry.transport == "http"


def test_json_roundtrip_stdio_unchanged(tmp_path):
    cfg_path = tmp_path / "test.mcp.json"
    entry = McpServerEntry(
        name="mytool",
        command="python",
        args=("-m", "mytool.server"),
        env={"DEBUG": "1"},
    )
    write_mcp_json(cfg_path, {"mytool": entry})

    read_entries = read_mcp_json(cfg_path)
    read_entry = read_entries["mytool"]
    assert read_entry.is_remote is False
    assert read_entry.command == "python"
    assert read_entry.args == ("-m", "mytool.server")
    assert read_entry.env["DEBUG"] == "1"


def test_json_mixed_stdio_and_remote(tmp_path):
    cfg_path = tmp_path / "test.mcp.json"
    entries = {
        "stdio_tool": McpServerEntry(
            name="stdio_tool",
            command="node",
            args=("--stdio",),
        ),
        "remote_tool": McpServerEntry(
            name="remote_tool",
            url="http://remote.example.com/mcp",
            transport="sse",
        ),
    }
    write_mcp_json(cfg_path, entries)

    read_entries = read_mcp_json(cfg_path)
    assert read_entries["stdio_tool"].is_remote is False
    assert read_entries["remote_tool"].is_remote is True
    assert read_entries["remote_tool"].transport == "sse"


def test_remove_remote_by_name(tmp_path):
    cfg_path = tmp_path / "test.mcp.json"
    entries = {
        "remote": McpServerEntry(
            name="remote",
            url="http://example.com/mcp",
        ),
        "stdio": McpServerEntry(
            name="stdio",
            command="node",
        ),
    }
    write_mcp_json(cfg_path, entries)

    assert remove_mcp_json(cfg_path, "remote") is True
    read_entries = read_mcp_json(cfg_path)
    assert "remote" not in read_entries
    assert "stdio" in read_entries


def test_remove_nonexistent(tmp_path):
    cfg_path = tmp_path / "test.mcp.json"
    assert remove_mcp_json(cfg_path, "nope") is False


def test_backward_compat_old_stdio_file(tmp_path):
    """Reading an old stdio-only .mcp.json still yields stdio entries."""
    cfg_path = tmp_path / "old.mcp.json"
    cfg_path.write_text(
        '{"mcpServers": {"old": {"command": "node", "args": ["--old"]}}}',
        encoding="utf-8",
    )
    entries = read_mcp_json(cfg_path)
    entry = entries["old"]
    assert entry.is_remote is False
    assert entry.command == "node"
    assert entry.args == ("--old",)
