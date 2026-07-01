"""Tests for MCP TOML format — OpenHands adapter (HM02 remote entry support)."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.adapters.openhands.toml_format import (
    read_mcp_toml,
    remove_mcp_toml,
    write_mcp_toml,
)
from audiagentic.foundation.mcp import McpServerEntry


def test_write_and_read_remote_entry(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    entries = {
        "hindsight": McpServerEntry(
            name="hindsight",
            url="http://10.10.100.10:8888/mcp",
            headers={"Authorization": "Bearer secret"},
            transport="http",
        )
    }
    write_mcp_toml(cfg, entries)

    result = read_mcp_toml(cfg)
    assert "hindsight" in result
    assert result["hindsight"].is_remote is True
    assert result["hindsight"].url == "http://10.10.100.10:8888/mcp"
    assert result["hindsight"].headers["Authorization"] == "Bearer secret"


def test_write_and_read_stdio_entry(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    entries = {
        "tool": McpServerEntry(
            name="tool",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-foo"),
        )
    }
    write_mcp_toml(cfg, entries)

    result = read_mcp_toml(cfg)
    assert "tool" in result
    assert result["tool"].is_remote is False
    assert result["tool"].command == "npx"


def test_remove_entry(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    entries = {
        "hindsight": McpServerEntry(name="hindsight", url="http://test/mcp"),
        "other": McpServerEntry(name="other", command="npx"),
    }
    write_mcp_toml(cfg, entries)

    removed = remove_mcp_toml(cfg, "hindsight")
    assert removed is True

    result = read_mcp_toml(cfg)
    assert "hindsight" not in result
    assert "other" in result


def test_preserves_existing_keys(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[other_section]\nkey = 'value'\n", encoding="utf-8")

    write_mcp_toml(cfg, {
        "hindsight": McpServerEntry(name="hindsight", url="http://test/mcp"),
    })

    import tomllib as _tomllib
    data = _tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["other_section"]["key"] == "value"
    assert "hindsight" in data["mcp_servers"]


def test_read_nonexistent_file(tmp_path: Path):
    result = read_mcp_toml(tmp_path / "missing.toml")
    assert result == {}


def test_remove_nonexistent_file(tmp_path: Path):
    result = remove_mcp_toml(tmp_path / "missing.toml", "hindsight")
    assert result is False


def test_roundtrip_remote_entry(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    original = {
        "hs": McpServerEntry(
            name="hs",
            url="http://host:9999/mcp",
            headers={"Authorization": "Bearer k", "X-Bank-Id": "bank1"},
            transport="sse",
        )
    }
    write_mcp_toml(cfg, original)

    result = read_mcp_toml(cfg)
    assert result["hs"].url == original["hs"].url
    assert result["hs"].transport == "sse"
    assert result["hs"].headers["X-Bank-Id"] == "bank1"


def test_entry_is_remote_property():
    remote = McpServerEntry(name="r", url="http://test/mcp")
    assert remote.is_remote is True

    stdio = McpServerEntry(name="s", command="npx")
    assert stdio.is_remote is False
