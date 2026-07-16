"""Test that enabling coding-lsp projects ag-lsp MCP into providers (not ag-lsp-mgmt)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.providers.contracts.lsp_mcp_projection import (
    LspMcpProjectionEntry,
    LspMcpProjectionRequest,
)
from audiagentic.components.providers.services.lsp_mcp_projection import (
    manage_lsp_mcp_projection_all,
)


class _Provider:
    def __init__(self, provider_id: str, *, has_mcp: bool = True, receive_lsp_mcp: bool = True, native: bool = False) -> None:
        self.provider_id = provider_id
        self.mcp_config = object() if has_mcp else None
        self.language_servers_config: object | None = object() if native else None
        self.on_lsp_enabled = None
        self.receive_lsp_mcp = receive_lsp_mcp

    def automation_capability(self, family_id: str):
        if family_id == "language-server-projection" and self.language_servers_config is not None:
            return object()
        if family_id == "lsp-mcp-projection" and self.mcp_config is not None and self.receive_lsp_mcp:
            return object()
        return None


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

        with patch("audiagentic.components.providers.descriptors.registry.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.feature_resolution.enabled_provider_ids", return_value=["claude"]):
                    # Only ag-lsp should be projected — no ag-lsp-mgmt
                    result = manage_lsp_mcp_projection_all(
                        tmp_path,
                        mode="apply",
                        request=LspMcpProjectionRequest(
                            managed_ids=("coding-lsp/ag-lsp",),
                            entries=(LspMcpProjectionEntry(
                                managed_id="coding-lsp/ag-lsp",
                                name="ag-lsp",
                                command="python",
                                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                            ),),
                        ),
                    )

        assert all(r.ok for r in result)
        claude_result = next((r for r in result if r.provider_id == "claude"), None)
        assert claude_result is not None
        assert "coding-lsp/ag-lsp" in claude_result.synced
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

        with patch("audiagentic.components.providers.descriptors.registry.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.feature_resolution.enabled_provider_ids", return_value=["skip-lsp"]):
                    result = manage_lsp_mcp_projection_all(
                        tmp_path,
                        mode="apply",
                        request=LspMcpProjectionRequest(
                            managed_ids=("coding-lsp/ag-lsp",),
                            entries=(LspMcpProjectionEntry(
                                managed_id="coding-lsp/ag-lsp",
                                name="ag-lsp",
                                command="python",
                            ),),
                        ),
                    )

        # Provider with receive_lsp_mcp=False is skipped by manage_lsp_mcp_projection_all
        assert all(r.provider_id != "skip-lsp" for r in result)
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
            "capabilities": frozenset(),
        })()
        spec.writer = staticmethod(_fake_writer)
        spec.remover = staticmethod(_fake_remover)
        codex.language_servers_config = spec

        from audiagentic.components.providers.contracts.language_server_projection import (
            LanguageServerEntry,
            LanguageServerProjectionRequest,
        )
        from audiagentic.components.providers.providers_api import manage_language_servers

        with patch("audiagentic.components.providers.descriptors.registry.get_descriptor") as mock_get:
            def _get(pid: str):
                return providers.get(pid)
            mock_get.side_effect = _get
            result = manage_language_servers(
                tmp_path,
                "codex",
                mode="apply",
                request=LanguageServerProjectionRequest(
                    entries={"python": LanguageServerEntry(language="python", command=["pyright-langserver", "--stdio"])}
                ),
            )

        assert result.ok is True
        assert captured["codex"] == ["python"]

    def test_sync_generic_lsp_empty_when_no_desired_entries(self, tmp_path: Path) -> None:
        """When no desired entries, providers should receive empty dicts."""
        providers = {
            "disabled": _Provider("disabled", native=False),
        }
        captured: dict[str, dict] = {}

        def _fake_sync(*, provider_id: str, project_root: Path, desired_entries: dict, managed_ids: set) -> dict:
            captured[provider_id] = desired_entries
            return {"ok": True}

        with patch("audiagentic.components.providers.descriptors.registry.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_mcp_projection.get_descriptor", side_effect=lambda pid: providers.get(pid)):
                with patch("audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                    with patch("audiagentic.components.providers.services.feature_resolution.enabled_provider_ids", return_value=["disabled"]):
                        result = manage_lsp_mcp_projection_all(
                            tmp_path,
                            mode="apply",
                            request=LspMcpProjectionRequest(
                                managed_ids=(),
                                entries=(),
                            ),
                        )

        assert all(r.ok for r in result)
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

        with patch("audiagentic.components.providers.descriptors.registry.all_descriptors", return_value=providers):
            with patch("audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset", _fake_sync):
                with patch("audiagentic.components.providers.services.feature_resolution.enabled_provider_ids", return_value=["opencode", "claude"]):
                    result = manage_lsp_mcp_projection_all(
                        tmp_path,
                        mode="apply",
                        request=LspMcpProjectionRequest(
                            managed_ids=("coding-lsp/ag-lsp",),
                            entries=(LspMcpProjectionEntry(
                                managed_id="coding-lsp/ag-lsp",
                                name="ag-lsp",
                                command="python",
                                args=("-m", "audiagentic.components.coding_lsp.lsp_mcp"),
                            ),),
                        ),
                    )

        assert all(r.ok for r in result)
        # opencode has both mcp_config and language_servers_config — should still receive MCP
        assert "opencode" in captured
        assert "coding-lsp/ag-lsp" in captured["opencode"]
        assert captured["opencode"]["coding-lsp/ag-lsp"] == "python"
        # claude should also receive it
        assert "claude" in captured
        assert "coding-lsp/ag-lsp" in captured["claude"]
