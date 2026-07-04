"""Test that enabling coding-lsp projects ag-lsp MCP into providers (not ag-lsp-mgmt)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.components.providers.services.lsp_projection import (
    sync_generic_lsp_mcp_to_provider_configs,
    sync_language_servers_to_provider_configs,
)
from audiagentic.foundation.mcp import McpServerEntry


class _Provider:
    def __init__(self, provider_id: str, *, has_mcp: bool = True, receive_lsp_mcp: bool = True, native: bool = False) -> None:
        self.provider_id = provider_id
        self.mcp_config = object() if has_mcp else None
        self.language_servers_config: object | None = object() if native else None
        self.on_lsp_enabled = None
        self.receive_lsp_mcp = receive_lsp_mcp


class TestEnableCodingLspAddsLspMcpToProviders:
    """Verify that enabling coding-lsp projects ag-lsp MCP into providers.

    ag-lsp-mgmt is NOT projected — it is for the AG CLI only.
    Only the generic-mcp projection from the active implementation descriptor
    (ag-lsp or blackwell-agent-lsp) is projected into providers.
    """

    def test_sync_generic_lsp_projects_only_ag_lsp_not_mgmt(self, tmp_path: Path) -> None:
        """Only ag-lsp managed entry should be projected — ag-lsp-mgmt must not appear."""
        providers = {
            "claude": _Provider("claude", native=False),
        }
        captured: dict[str, dict] = {}

        def _fake_sync(*, provider_id: str, project_root: Path, desired_entries: dict, managed_ids: set) -> dict:
            entries_map: dict[str, tuple[str, str]] = {}
            for k, (n, e) in desired_entries.items():
                entries_map[k] = (n, e.command)
            captured[provider_id] = {
                "entries": entries_map,
                "managed_ids": managed_ids,
            }
            return {"ok": True}

        with patch("audiagentic.components.providers.services.lsp_projection.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.lsp_projection.enabled_provider_ids", return_value=["claude"]):
                    # Only ag-lsp should be projected — no ag-lsp-mgmt
                    result = sync_generic_lsp_mcp_to_provider_configs(
                        tmp_path,
                        {"coding-lsp/ag-lsp": ("ag-lsp", McpServerEntry(name="ag-lsp", command="python", args=("-m", "audiagentic.components.coding_lsp.lsp_mcp")))},
                        {"coding-lsp/ag-lsp"},
                    )

        assert result["ok"] is True
        assert "claude" in result["synced"]
        entries = captured["claude"]["entries"]  # type: ignore[union-attr]
        assert "coding-lsp/ag-lsp" in entries
        # ag-lsp-mgmt must NOT be in the projected entries
        assert "coding-lsp/ag-lsp-mgmt" not in entries

    def test_sync_generic_lsp_skips_provider_with_receive_lsp_mcp_false(self, tmp_path: Path) -> None:
        """Providers with receive_lsp_mcp=False should not receive LSP MCP projections."""
        providers = {
            "skip-lsp": _Provider("skip-lsp", receive_lsp_mcp=False),
        }
        captured: dict[str, object] = {}

        def _fake_sync(*, provider_id: str, project_root: Path, desired_entries: dict, managed_ids: set) -> dict:
            captured[provider_id] = True
            return {"ok": True}

        with patch("audiagentic.components.providers.services.lsp_projection.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.lsp_projection.enabled_provider_ids", return_value=["skip-lsp"]):
                    result = sync_generic_lsp_mcp_to_provider_configs(
                        tmp_path,
                        {"coding-lsp/ag-lsp": ("ag-lsp", McpServerEntry(name="ag-lsp", command="python"))},
                        {"coding-lsp/ag-lsp"},
                    )

        assert result["ok"] is True
        assert "skip-lsp" in result["skipped"]
        assert "skip-lsp" not in captured

    def test_sync_language_servers_to_native_provider(self, tmp_path: Path) -> None:
        """Native providers (with language_servers_config) receive language server entries, not generic MCP."""
        providers = {
            "codex": _Provider("codex", native=True),
            "claude": _Provider("claude", native=False),
        }
        captured: dict[str, list] = {}

        def _fake_writer(path: Path, servers: dict) -> None:
            captured["codex"] = list(servers.keys())

        def _fake_remover(path: Path, lang: str) -> bool:
            return False

        codex = providers["codex"]
        spec = type("_Spec", (), {
            "config_path": tmp_path / "config.json",
        })()
        spec.writer = staticmethod(_fake_writer)
        spec.remover = staticmethod(_fake_remover)
        codex.language_servers_config = spec

        with patch("audiagentic.components.providers.services.lsp_projection.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_projection.enabled_provider_ids", return_value=["codex"]):
                result = sync_language_servers_to_provider_configs(
                    tmp_path,
                    {"python": LanguageServerEntry(language="python", command=["pyright-langserver", "--stdio"])},
                )

        assert result["ok"] is True
        assert "codex" in result["synced"]
        assert captured["codex"] == ["python"]
        assert "claude" in result["skipped"]

    def test_sync_generic_lsp_empty_when_no_desired_entries(self, tmp_path: Path) -> None:
        """When no desired entries, providers should receive empty dicts."""
        providers = {
            "disabled": _Provider("disabled", native=False),
        }
        captured: dict[str, dict] = {}

        def _fake_sync(*, provider_id: str, project_root: Path, desired_entries: dict, managed_ids: set) -> dict:
            captured[provider_id] = desired_entries
            return {"ok": True}

        with patch("audiagentic.components.providers.services.lsp_projection.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                result = sync_generic_lsp_mcp_to_provider_configs(
                    tmp_path,
                    {},
                    set(),
                )

        assert result["ok"] is True
        assert captured["disabled"] == {}

    def test_sync_generic_lsp_to_provider_with_both_mcp_and_language_servers_config(self, tmp_path: Path) -> None:
        """Providers with both mcp_config and language_servers_config (like opencode) should receive MCP projections."""
        providers = {
            "opencode": _Provider("opencode", native=True, receive_lsp_mcp=True),
            "claude": _Provider("claude", native=False, receive_lsp_mcp=True),
        }
        captured: dict[str, dict] = {}

        def _fake_sync(*, provider_id: str, project_root: Path, desired_entries: dict, managed_ids: set) -> dict:
            entries_map: dict[str, str] = {k: e.command for k, (_, e) in desired_entries.items()}
            captured[provider_id] = entries_map
            return {"ok": True}

        with patch("audiagentic.components.providers.services.lsp_projection.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.lsp_projection.enabled_provider_ids", return_value=["opencode", "claude"]):
                    result = sync_generic_lsp_mcp_to_provider_configs(
                        tmp_path,
                        {"coding-lsp/ag-lsp": ("ag-lsp", McpServerEntry(name="ag-lsp", command="python", args=("-m", "audiagentic.components.coding_lsp.lsp_mcp")))},
                        {"coding-lsp/ag-lsp"},
                    )

        assert result["ok"] is True
        # opencode has both mcp_config and language_servers_config — should still receive MCP
        assert "opencode" in captured
        assert "coding-lsp/ag-lsp" in captured["opencode"]
        assert captured["opencode"]["coding-lsp/ag-lsp"] == "python"
        # claude should also receive it
        assert "claude" in captured
        assert "coding-lsp/ag-lsp" in captured["claude"]
