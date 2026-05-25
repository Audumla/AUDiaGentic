"""Unit tests for generic provider MCP config management."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.optional.providers.mcp_config import (
    McpServerEntry,
    read_mcp_servers,
    remove_mcp_server,
    write_mcp_servers,
)
from audiagentic.components.optional.providers.services.lifecycle import (
    add_provider_mcp_server,
    list_provider_mcp_servers,
    reload_provider_mcp,
    remove_provider_mcp_server,
)

# --- mcp_config.py format handler tests ---

class TestMcpJsonFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_mcp_servers(tmp_path / ".mcp.json", "mcp-json")
        assert result == {}

    def test_write_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="my-server", command="uvx", args=("my-tool",))
        write_mcp_servers(path, {"my-server": entry}, "mcp-json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["command"] == "uvx"
        assert data["mcpServers"]["my-server"]["args"] == ["my-tool"]

    def test_write_preserves_existing_keys(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"existing": {"command": "old", "args": []}}, "settings": {"x": 1}}))
        entry = McpServerEntry(name="new-server", command="uvx", args=())
        write_mcp_servers(path, {"new-server": entry}, "mcp-json")
        data = json.loads(path.read_text())
        assert "existing" in data["mcpServers"]
        assert "new-server" in data["mcpServers"]
        assert data["settings"] == {"x": 1}

    def test_write_omits_empty_env(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="s", command="cmd", args=())
        write_mcp_servers(path, {"s": entry}, "mcp-json")
        data = json.loads(path.read_text())
        assert "env" not in data["mcpServers"]["s"]

    def test_write_includes_env_when_set(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="s", command="cmd", args=(), env={"FOO": "bar"})
        write_mcp_servers(path, {"s": entry}, "mcp-json")
        data = json.loads(path.read_text())
        assert data["mcpServers"]["s"]["env"] == {"FOO": "bar"}

    def test_remove_existing_entry(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"a": {"command": "x", "args": []}, "b": {"command": "y", "args": []}}}))
        removed = remove_mcp_server(path, "a", "mcp-json")
        assert removed is True
        data = json.loads(path.read_text())
        assert "a" not in data["mcpServers"]
        assert "b" in data["mcpServers"]

    def test_remove_missing_entry_returns_false(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {}}))
        assert remove_mcp_server(path, "nonexistent", "mcp-json") is False

    def test_remove_missing_file_returns_false(self, tmp_path: Path) -> None:
        assert remove_mcp_server(tmp_path / ".mcp.json", "x", "mcp-json") is False

    def test_read_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="srv", command="python", args=("-m", "mod"), env={"K": "V"})
        write_mcp_servers(path, {"srv": entry}, "mcp-json")
        result = read_mcp_servers(path, "mcp-json")
        assert "srv" in result
        assert result["srv"].command == "python"
        assert result["srv"].args == ("-m", "mod")
        assert result["srv"].env == {"K": "V"}


class TestGooseYamlFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_mcp_servers(tmp_path / "config.yaml", "goose-yaml")
        assert result == {}

    def test_write_creates_extension_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        entry = McpServerEntry(name="my-ext", command="uvx", args=("tool",))
        write_mcp_servers(path, {"my-ext": entry}, "goose-yaml")
        result = read_mcp_servers(path, "goose-yaml")
        assert "my-ext" in result
        assert result["my-ext"].command == "uvx"

    def test_write_preserves_non_stdio_extensions(self, tmp_path: Path) -> None:
        import yaml
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump({"extensions": [{"name": "other", "type": "builtin"}]}))
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_mcp_servers(path, {"srv": entry}, "goose-yaml")
        import yaml as _yaml
        data = _yaml.safe_load(path.read_text())
        names = [e["name"] for e in data["extensions"]]
        assert "other" in names
        assert "srv" in names

    def test_remove_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_mcp_servers(path, {"srv": entry}, "goose-yaml")
        removed = remove_mcp_server(path, "srv", "goose-yaml")
        assert removed is True
        result = read_mcp_servers(path, "goose-yaml")
        assert "srv" not in result


class TestContinueJsonFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_mcp_servers(tmp_path / "config.json", "continue-json")
        assert result == {}

    def test_write_creates_server_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        entry = McpServerEntry(name="srv", command="uvx", args=("tool",))
        write_mcp_servers(path, {"srv": entry}, "continue-json")
        data = json.loads(path.read_text())
        assert any(s["name"] == "srv" for s in data["mcpServers"])

    def test_write_preserves_existing_servers(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"mcpServers": [{"name": "existing", "command": "x", "args": []}]}))
        entry = McpServerEntry(name="new", command="y", args=())
        write_mcp_servers(path, {"new": entry}, "continue-json")
        data = json.loads(path.read_text())
        names = [s["name"] for s in data["mcpServers"]]
        assert "existing" in names
        assert "new" in names

    def test_remove_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_mcp_servers(path, {"srv": entry}, "continue-json")
        removed = remove_mcp_server(path, "srv", "continue-json")
        assert removed is True
        result = read_mcp_servers(path, "continue-json")
        assert "srv" not in result


class TestUnsupportedFormat:
    def test_read_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            read_mcp_servers(tmp_path / "f", "unknown-format")

    def test_write_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            write_mcp_servers(tmp_path / "f", {}, "unknown-format")

    def test_remove_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            remove_mcp_server(tmp_path / "f", "x", "unknown-format")


# --- lifecycle function tests ---

class TestAddProviderMcpServer:
    def test_adds_entry_to_mcp_json(self, tmp_path: Path) -> None:
        result = add_provider_mcp_server("claude", "my-srv", "uvx", tmp_path, args=("my-tool",))
        assert result["ok"] is True
        mcp = tmp_path / ".mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "my-srv" in data["mcpServers"]
        assert data["mcpServers"]["my-srv"]["command"] == "uvx"

    def test_file_watch_provider_reports_auto_refreshed(self, tmp_path: Path) -> None:
        result = add_provider_mcp_server("claude", "srv", "cmd", tmp_path)
        assert result["auto_refreshed"] is True
        assert result["method"] == "file-watch"

    def test_returns_error_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = add_provider_mcp_server("aider", "srv", "cmd", tmp_path)
        assert result["ok"] is False
        assert "no mcp_config" in result["error"]

    def test_adds_env_when_provided(self, tmp_path: Path) -> None:
        add_provider_mcp_server("claude", "srv", "cmd", tmp_path, env={"KEY": "val"})
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["srv"]["env"] == {"KEY": "val"}

    def test_updates_existing_entry(self, tmp_path: Path) -> None:
        add_provider_mcp_server("claude", "srv", "old-cmd", tmp_path)
        add_provider_mcp_server("claude", "srv", "new-cmd", tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["srv"]["command"] == "new-cmd"


class TestRemoveProviderMcpServer:
    def test_removes_existing_entry(self, tmp_path: Path) -> None:
        add_provider_mcp_server("claude", "srv", "cmd", tmp_path)
        result = remove_provider_mcp_server("claude", "srv", tmp_path)
        assert result["ok"] is True
        assert result["removed"] is True
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert "srv" not in data["mcpServers"]

    def test_remove_missing_entry_ok_not_removed(self, tmp_path: Path) -> None:
        result = remove_provider_mcp_server("claude", "nonexistent", tmp_path)
        assert result["ok"] is True
        assert result["removed"] is False

    def test_returns_error_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = remove_provider_mcp_server("aider", "srv", tmp_path)
        assert result["ok"] is False


class TestListProviderMcpServers:
    def test_lists_entries(self, tmp_path: Path) -> None:
        add_provider_mcp_server("claude", "srv-a", "cmd-a", tmp_path)
        add_provider_mcp_server("claude", "srv-b", "cmd-b", tmp_path)
        result = list_provider_mcp_servers("claude", tmp_path)
        assert result["ok"] is True
        names = [s["name"] for s in result["servers"]]
        assert "srv-a" in names
        assert "srv-b" in names

    def test_empty_when_no_config_file(self, tmp_path: Path) -> None:
        result = list_provider_mcp_servers("claude", tmp_path)
        assert result["ok"] is True
        assert result["servers"] == []
        assert result["config_exists"] is False

    def test_skipped_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = list_provider_mcp_servers("aider", tmp_path)
        assert result["ok"] is True
        assert "skipped" in result


class TestReloadProviderMcp:
    def test_file_watch_returns_auto_refreshed(self, tmp_path: Path) -> None:
        result = reload_provider_mcp("claude", tmp_path)
        assert result["ok"] is True
        assert result["auto_refreshed"] is True
        assert result["method"] == "file-watch"

    def test_restart_required_returns_action_needed(self, tmp_path: Path) -> None:
        result = reload_provider_mcp("gemini", tmp_path)
        assert result["ok"] is True
        assert result["auto_refreshed"] is False
        assert result["method"] == "restart-required"
        assert "action_needed" in result

    def test_pi_restart_required_returns_action_needed(self, tmp_path: Path) -> None:
        result = reload_provider_mcp("pi", tmp_path)
        assert result["ok"] is True
        assert result["auto_refreshed"] is False
        assert result["method"] == "restart-required"
        assert "action_needed" in result

    def test_error_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = reload_provider_mcp("aider", tmp_path)
        assert result["ok"] is False


class TestMcpConfigSpecOnDescriptors:
    def test_file_watch_providers_have_mcp_json(self) -> None:
        from audiagentic.components.optional.providers.descriptors.registry import get_descriptor
        for pid in ("claude", "opencode", "qwen"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is not None, f"{pid} missing mcp_config"
            assert desc.mcp_config.format == "mcp-json"
            assert desc.mcp_config.refresh_mode == "file-watch"

    def test_restart_required_providers(self) -> None:
        from audiagentic.components.optional.providers.descriptors.registry import get_descriptor
        for pid in ("gemini", "cline", "codex", "copilot", "roo", "pi"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is not None, f"{pid} missing mcp_config"
            assert desc.mcp_config.refresh_mode == "restart-required"

    def test_special_format_providers(self) -> None:
        from audiagentic.components.optional.providers.descriptors.registry import get_descriptor
        goose = get_descriptor("goose")
        assert goose.mcp_config.format == "goose-yaml"
        assert goose.mcp_config.config_path == ".goose/config.yaml"
        cont = get_descriptor("continue")
        assert cont.mcp_config.format == "continue-json"
        assert cont.mcp_config.config_path == ".continue/config.json"
        gem = get_descriptor("gemini")
        assert gem.mcp_config.config_path == ".gemini/settings.json"

    def test_providers_without_mcp_config(self) -> None:
        from audiagentic.components.optional.providers.descriptors.registry import get_descriptor
        for pid in ("aider", "plandex", "openhands", "local-openai"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is None, f"{pid} should have no mcp_config"

    def test_goose_and_continue_have_restart_required(self) -> None:
        from audiagentic.components.optional.providers.descriptors.registry import get_descriptor
        for pid in ("goose", "continue"):
            desc = get_descriptor(pid)
            assert desc.mcp_config.refresh_mode == "restart-required"
