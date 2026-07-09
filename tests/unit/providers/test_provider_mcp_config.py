"""Unit tests for generic provider MCP config management."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.codex.mcp_format import (
    read_codex_toml,
    remove_codex_toml,
    write_codex_toml,
)
from audiagentic.components.providers.adapters.continue_.mcp_format import (
    read_continue_json,
    remove_continue_json,
    write_continue_json,
)
from audiagentic.components.providers.adapters.goose.mcp_format import (
    read_goose_yaml,
    remove_goose_yaml,
    write_goose_yaml,
)
from audiagentic.components.providers.services.mcp import (
    add_provider_mcp_server,
    list_provider_mcp_servers,
    reload_provider_mcp,
    remove_provider_mcp_server,
    sync_managed_provider_mcp,
    sync_managed_provider_mcp_subset,
)
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)

# --- format handler tests ---

class TestMcpJsonFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_mcp_json(tmp_path / ".mcp.json")
        assert result == {}

    def test_write_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="my-server", command="uvx", args=("my-tool",))
        write_mcp_json(path, {"my-server": entry})
        assert path.exists()
        data = json.loads(path.read_text())
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["command"] == "uvx"
        assert data["mcpServers"]["my-server"]["args"] == ["my-tool"]

    def test_write_preserves_existing_keys(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"existing": {"command": "old", "args": []}}, "settings": {"x": 1}}))
        entry = McpServerEntry(name="new-server", command="uvx", args=())
        write_mcp_json(path, {"new-server": entry})
        data = json.loads(path.read_text())
        assert "existing" in data["mcpServers"]
        assert "new-server" in data["mcpServers"]
        assert data["settings"] == {"x": 1}

    def test_write_omits_empty_env(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="s", command="cmd", args=())
        write_mcp_json(path, {"s": entry})
        data = json.loads(path.read_text())
        assert "env" not in data["mcpServers"]["s"]

    def test_write_includes_env_when_set(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="s", command="cmd", args=(), env={"FOO": "bar"})
        write_mcp_json(path, {"s": entry})
        data = json.loads(path.read_text())
        assert data["mcpServers"]["s"]["env"] == {"FOO": "bar"}

    def test_remove_existing_entry(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"a": {"command": "x", "args": []}, "b": {"command": "y", "args": []}}}))
        removed = remove_mcp_json(path, "a")
        assert removed is True
        data = json.loads(path.read_text())
        assert "a" not in data["mcpServers"]
        assert "b" in data["mcpServers"]

    def test_remove_missing_entry_returns_false(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {}}))
        assert remove_mcp_json(path, "nonexistent") is False

    def test_remove_missing_file_returns_false(self, tmp_path: Path) -> None:
        assert remove_mcp_json(tmp_path / ".mcp.json", "x") is False

    def test_read_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / ".mcp.json"
        entry = McpServerEntry(name="srv", command="python", args=("-m", "mod"), env={"K": "V"})
        write_mcp_json(path, {"srv": entry})
        result = read_mcp_json(path)
        assert "srv" in result
        assert result["srv"].command == "python"
        assert result["srv"].args == ("-m", "mod")
        assert result["srv"].env == {"K": "V"}

    def test_write_resolves_python_for_audiagentic_entry(self, tmp_path: Path) -> None:
        """External tools (cline, roo, ...) read this file directly and cannot
        resolve the portability placeholder — the interpreter path must be
        written resolved, never as ``__AUDIAGENTIC_PYTHON__``."""
        import sys

        path = tmp_path / ".cline" / "mcp.json"
        path.parent.mkdir()
        entry = McpServerEntry(
            name="ag-planning",
            command=sys.executable,
            args=("-m", "audiagentic.launcher", "mcp", "audiagentic.components.planning.planning_mcp"),
        )
        write_mcp_json(path, {"ag-planning": entry})
        data = json.loads(path.read_text())
        command = data["mcpServers"]["ag-planning"]["command"]
        assert command == sys.executable
        assert command != "__AUDIAGENTIC_PYTHON__"

    def test_write_resolves_preexisting_placeholder(self, tmp_path: Path) -> None:
        """A file already containing the placeholder is healed on next write."""
        import sys

        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"ag-planning": {
            "command": "__AUDIAGENTIC_PYTHON__",
            "args": ["-m", "audiagentic.launcher"],
        }}}))
        # Read resolves the placeholder; writing it back must persist a real path.
        entries = read_mcp_json(path)
        write_mcp_json(path, entries)
        data = json.loads(path.read_text())
        assert data["mcpServers"]["ag-planning"]["command"] == sys.executable


class TestGooseYamlFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_goose_yaml(tmp_path / "config.yaml")
        assert result == {}

    def test_write_creates_extension_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        entry = McpServerEntry(name="my-ext", command="uvx", args=("tool",))
        write_goose_yaml(path, {"my-ext": entry})
        result = read_goose_yaml(path)
        assert "my-ext" in result
        assert result["my-ext"].command == "uvx"

    def test_write_preserves_non_stdio_extensions(self, tmp_path: Path) -> None:
        import yaml
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump({"extensions": [{"name": "other", "type": "builtin"}]}))
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_goose_yaml(path, {"srv": entry})
        import yaml as _yaml
        data = _yaml.safe_load(path.read_text())
        names = [e["name"] for e in data["extensions"]]
        assert "other" in names
        assert "srv" in names

    def test_remove_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_goose_yaml(path, {"srv": entry})
        removed = remove_goose_yaml(path, "srv")
        assert removed is True
        result = read_goose_yaml(path)
        assert "srv" not in result


class TestContinueJsonFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_continue_json(tmp_path / "config.json")
        assert result == {}

    def test_write_creates_server_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        entry = McpServerEntry(name="srv", command="uvx", args=("tool",))
        write_continue_json(path, {"srv": entry})
        data = json.loads(path.read_text())
        assert any(s["name"] == "srv" for s in data["mcpServers"])

    def test_write_preserves_existing_servers(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"mcpServers": [{"name": "existing", "command": "x", "args": []}]}))
        entry = McpServerEntry(name="new", command="y", args=())
        write_continue_json(path, {"new": entry})
        data = json.loads(path.read_text())
        names = [s["name"] for s in data["mcpServers"]]
        assert "existing" in names
        assert "new" in names

    def test_remove_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        entry = McpServerEntry(name="srv", command="cmd", args=())
        write_continue_json(path, {"srv": entry})
        removed = remove_continue_json(path, "srv")
        assert removed is True
        result = read_continue_json(path)
        assert "srv" not in result


class TestCodexTomlFormat:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_codex_toml(tmp_path / ".codex" / "config.toml")
        assert result == {}

    def test_write_creates_codex_server_entry(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "config.toml"
        entry = McpServerEntry(name="srv", command="python", args=("-m", "mod"))
        write_codex_toml(path, {"srv": entry})
        data = path.read_text(encoding="utf-8")
        assert "[mcp_servers.srv]" in data
        assert "command = 'python'" in data
        assert "args = ['-m', 'mod']" in data
        assert "enabled = true" in data

    def test_write_preserves_existing_codex_settings(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            'model = "gpt-5.4"\n\n[features]\nexperimental_windows_sandbox = true\n',
            encoding="utf-8",
        )
        entry = McpServerEntry(name="srv", command="python", args=("-m", "mod"))
        write_codex_toml(path, {"srv": entry})
        data = path.read_text(encoding="utf-8")
        assert "model = 'gpt-5.4'" in data
        assert "[features]" in data
        assert "[mcp_servers.srv]" in data

    def test_remove_existing_codex_entry(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "config.toml"
        entry = McpServerEntry(name="srv", command="python", args=("-m", "mod"))
        write_codex_toml(path, {"srv": entry})
        removed = remove_codex_toml(path, "srv")
        assert removed is True
        result = read_codex_toml(path)
        assert "srv" not in result

    def test_write_windows_paths_as_valid_toml(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "config.toml"
        entry = McpServerEntry(
            name="srv",
            command=r"C:\Users\mgs\AppData\Local\python.exe",
            args=("-m", "mod"),
            env={"AUDIAGENTIC_REPO_ROOT": r"H:\development\projects\AUDia\AUDiaGentic"},
        )

        write_codex_toml(path, {"srv": entry})

        result = read_codex_toml(path)
        assert result["srv"].command == entry.command
        assert result["srv"].env == entry.env



class TestAddProviderMcpServer:
    def test_adds_entry_to_mcp_json(self, tmp_path: Path, claude_home: Path) -> None:
        result = add_provider_mcp_server("claude", "my-srv", "uvx", tmp_path, args=("my-tool",))
        assert result["ok"] is True
        mcp = claude_home / ".claude" / "mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "my-srv" in data["mcpServers"]
        assert data["mcpServers"]["my-srv"]["command"] == "uvx"

    def test_file_watch_provider_reports_auto_refreshed(self, tmp_path: Path, claude_home: Path) -> None:
        result = add_provider_mcp_server("claude", "srv", "cmd", tmp_path)
        assert result["auto_refreshed"] is True
        assert result["method"] == "file-watch"

    def test_returns_error_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = add_provider_mcp_server("aider", "srv", "cmd", tmp_path)
        assert result["ok"] is False
        assert "no mcp_config" in result["error"]

    def test_adds_env_when_provided(self, tmp_path: Path, claude_home: Path) -> None:
        add_provider_mcp_server("claude", "srv", "cmd", tmp_path, env={"KEY": "val"})
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert data["mcpServers"]["srv"]["env"] == {"KEY": "val"}

    def test_updates_existing_entry(self, tmp_path: Path, claude_home: Path) -> None:
        add_provider_mcp_server("claude", "srv", "old-cmd", tmp_path)
        add_provider_mcp_server("claude", "srv", "new-cmd", tmp_path)
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert data["mcpServers"]["srv"]["command"] == "new-cmd"

    def test_adds_entry_to_codex_toml(self, tmp_path: Path) -> None:
        result = add_provider_mcp_server("codex", "my-srv", "python", tmp_path, args=("-m", "mod"))
        assert result["ok"] is True
        path = tmp_path / ".codex" / "config.toml"
        assert path.exists()
        data = path.read_text(encoding="utf-8")
        assert "[mcp_servers.my-srv]" in data
        assert "command = 'python'" in data


class TestRemoveProviderMcpServer:
    def test_removes_existing_entry(self, tmp_path: Path, claude_home: Path) -> None:
        add_provider_mcp_server("claude", "srv", "cmd", tmp_path)
        result = remove_provider_mcp_server("claude", "srv", tmp_path)
        assert result["ok"] is True
        assert result["removed"] is True
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert "srv" not in data["mcpServers"]

    def test_remove_missing_entry_ok_not_removed(self, tmp_path: Path) -> None:
        result = remove_provider_mcp_server("claude", "nonexistent", tmp_path)
        assert result["ok"] is True
        assert result["removed"] is False

    def test_returns_error_for_provider_without_mcp_config(self, tmp_path: Path) -> None:
        result = remove_provider_mcp_server("aider", "srv", tmp_path)
        assert result["ok"] is False


class TestListProviderMcpServers:
    def test_lists_entries(self, tmp_path: Path, claude_home: Path) -> None:
        add_provider_mcp_server("claude", "srv-a", "cmd-a", tmp_path)
        add_provider_mcp_server("claude", "srv-b", "cmd-b", tmp_path)
        result = list_provider_mcp_servers("claude", tmp_path)
        assert result["ok"] is True
        names = [s["name"] for s in result["servers"]]
        assert "srv-a" in names
        assert "srv-b" in names

    def test_empty_when_no_config_file(self, tmp_path: Path, claude_home: Path) -> None:
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


class TestSyncManagedProviderMcp:
    def test_preserves_external_entries(self, tmp_path: Path, claude_home: Path) -> None:
        path = claude_home / ".claude" / "mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "mcpServers": {
                "external-server": {"command": "node", "args": ["custom.js"]},
            }
        }))

        entry = McpServerEntry(name="ag-project-mgmt", command="python", args=("-m", "mod"))
        result = sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {"project.ag-project-mgmt": ("ag-project-mgmt", entry)},
        )

        assert result["ok"] is True
        data = json.loads(path.read_text())
        assert "external-server" in data["mcpServers"]
        assert "ag-project-mgmt" in data["mcpServers"]

    def test_renames_owned_entry_by_managed_id(self, tmp_path: Path, claude_home: Path) -> None:
        old_entry = McpServerEntry(name="ag-project-mgmt", command="python", args=("-m", "old"))
        sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {"project.ag-project-mgmt": ("ag-project-mgmt", old_entry)},
        )

        new_entry = McpServerEntry(name="ag-project", command="python", args=("-m", "new"))
        result = sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {"project.ag-project-mgmt": ("ag-project", new_entry)},
        )

        assert result["ok"] is True
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert "ag-project" in data["mcpServers"]
        assert "ag-project-mgmt" not in data["mcpServers"]

    def test_adopts_unregistered_entry_with_matching_name(self, tmp_path: Path, claude_home: Path) -> None:
        """AUDiaGentic takes ownership of any entry whose name matches a managed server.

        An entry present in the config file but not in the managed registry was
        written by an older code path. The managed sync must adopt it (overwrite
        with the correct entry and record ownership) rather than skip it.
        This prevents orphaned entries from blocking future syncs.
        """
        path = claude_home / ".claude" / "mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "mcpServers": {
                "ag-project-mgmt": {"command": "old", "args": ["legacy.js"]},
            }
        }))

        entry = McpServerEntry(name="ag-project-mgmt", command="python", args=("-m", "mod"))
        result = sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {"project.ag-project-mgmt": ("ag-project-mgmt", entry)},
        )

        assert result["ok"] is True
        assert not result["collisions"]
        data = json.loads(path.read_text())
        assert data["mcpServers"]["ag-project-mgmt"]["command"] == "python"


class TestSyncManagedProviderMcpSubset:
    def test_prunes_only_targeted_managed_entries(self, tmp_path: Path, claude_home: Path) -> None:
        sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {
                "ledger/ag-ledger": (
                    "ag-ledger",
                    McpServerEntry(name="ag-ledger", command="python", args=("-m", "ledger")),
                ),
                "coding-lsp/ag-lsp": (
                    "ag-lsp",
                    McpServerEntry(name="ag-lsp", command="python", args=("-m", "lsp")),
                ),
            },
        )

        result = sync_managed_provider_mcp_subset(
            "claude",
            tmp_path,
            desired_entries={},
            managed_ids={"coding-lsp/ag-lsp"},
        )

        assert result["ok"] is True
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert "ag-ledger" in data["mcpServers"]
        assert "ag-lsp" not in data["mcpServers"]

    def test_updates_only_targeted_subset(self, tmp_path: Path, claude_home: Path) -> None:
        ledger = McpServerEntry(name="ag-ledger", command="python", args=("-m", "ledger"))
        lsp = McpServerEntry(name="ag-lsp", command="python", args=("-m", "old.lsp"))
        sync_managed_provider_mcp(
            "claude",
            tmp_path,
            {
                "ledger/ag-ledger": ("ag-ledger", ledger),
                "coding-lsp/ag-lsp": ("ag-lsp", lsp),
            },
        )

        renamed = McpServerEntry(name="ag-lsp2", command="python", args=("-m", "new.lsp"))
        result = sync_managed_provider_mcp_subset(
            "claude",
            tmp_path,
            desired_entries={"coding-lsp/ag-lsp": ("ag-lsp2", renamed)},
            managed_ids={"coding-lsp/ag-lsp"},
        )

        assert result["ok"] is True
        data = json.loads((claude_home / ".claude" / "mcp.json").read_text())
        assert "ag-ledger" in data["mcpServers"]
        assert "ag-lsp" not in data["mcpServers"]
        assert "ag-lsp2" in data["mcpServers"]


class TestMcpConfigSpecOnDescriptors:
    def test_file_watch_providers_have_mcp_json(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        for pid in ("claude", "qwen"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is not None, f"{pid} missing mcp_config"
            assert desc.mcp_config.format == "mcp-json", f"{pid}: expected mcp-json, got {desc.mcp_config.format}"
            assert desc.mcp_config.refresh_mode == "file-watch"
        # opencode uses its own JSON format
        opencode = get_descriptor("opencode")
        assert opencode.mcp_config is not None
        assert opencode.mcp_config.format == "opencode-mcp"
        assert opencode.mcp_config.refresh_mode == "file-watch"

    def test_restart_required_providers(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        for pid in ("gemini", "cline", "codex", "copilot", "roo", "pi"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is not None, f"{pid} missing mcp_config"
            assert desc.mcp_config.refresh_mode == "restart-required"

    def test_special_format_providers(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        goose = get_descriptor("goose")
        assert goose.mcp_config.format == "goose-yaml"
        assert goose.mcp_config.config_path == ".goose/config.yaml"
        cont = get_descriptor("continue")
        assert cont.mcp_config.format == "continue-json"
        assert cont.mcp_config.config_path == ".continue/config.json"
        gem = get_descriptor("gemini")
        assert gem.mcp_config.config_path == ".gemini/settings.json"
        cline = get_descriptor("cline")
        assert cline.mcp_config.config_path == ".cline/mcp.json"
        codex = get_descriptor("codex")
        assert codex.mcp_config.format == "codex-toml"
        assert codex.mcp_config.config_path == ".codex/config.toml"

    def test_providers_without_mcp_config(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        for pid in ("aider", "plandex", "local-openai"):
            desc = get_descriptor(pid)
            assert desc.mcp_config is None, f"{pid} should have no mcp_config"


class TestOpenhandsMcpConfig:
    def test_openhands_has_toml_mcp_config(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor

        desc = get_descriptor("openhands")
        assert desc.mcp_config is not None
        assert desc.mcp_config.config_path == ".openhands/config.toml"
        assert desc.mcp_config.format == "mcp-toml"
        assert desc.mcp_config.refresh_mode == "restart-required"


class TestOpenhandsTomlRoundtrip:
    def test_toml_remote_entry_roundtrip(self, tmp_path: Path) -> None:
        from audiagentic.components.providers.adapters.openhands.toml_format import (
            read_mcp_toml,
            write_mcp_toml,
        )
        from audiagentic.foundation.mcp import McpServerEntry

        cfg = tmp_path / "config.toml"
        write_mcp_toml(cfg, {
            "hindsight": McpServerEntry(
                name="hindsight",
                url="http://host:8888/mcp",
                headers={"Authorization": "Bearer k"},
                transport="http",
            ),
        })

        result = read_mcp_toml(cfg)
        assert result["hindsight"].is_remote is True
        assert result["hindsight"].url == "http://host:8888/mcp"

    def test_goose_and_continue_have_restart_required(self) -> None:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        for pid in ("goose", "continue"):
            desc = get_descriptor(pid)
            assert desc.mcp_config.refresh_mode == "restart-required"


class TestOpencodeMcpPath:
    def test_explicit_root_resolved_absolute(self, tmp_path: Path) -> None:
        from audiagentic.runtime.harness.opencode.mcp_format import opencode_mcp_path
        path = opencode_mcp_path(tmp_path)
        assert path.is_absolute()
        assert path == (tmp_path / ".mcp.json").resolve()

    def test_relative_root_resolved_absolute(self, tmp_path: Path) -> None:
        from audiagentic.runtime.harness.opencode.mcp_format import opencode_mcp_path
        rel = Path("sub") / "proj"
        path = opencode_mcp_path(rel)
        assert path.is_absolute()
        assert path == (Path.cwd() / rel / ".mcp.json").resolve()

    def test_env_fallback_resolved_absolute(self, tmp_path: Path, monkeypatch) -> None:
        from audiagentic.runtime.harness.opencode.mcp_format import opencode_mcp_path
        monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
        path = opencode_mcp_path()
        assert path.is_absolute()
        assert path == (tmp_path / ".mcp.json").resolve()

    def test_default_dot_fallback_resolved_absolute(self, monkeypatch) -> None:
        from audiagentic.runtime.harness.opencode.mcp_format import opencode_mcp_path
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        path = opencode_mcp_path()
        assert path.is_absolute()
        assert path == (Path.cwd() / ".mcp.json").resolve()
