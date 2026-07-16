from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.language_servers_sync import (
    sync_generic_lsp_mcp_to_providers,
)
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
    ImplementationState,
)
from audiagentic.foundation.features.state import set_feature_state, set_implementation_state


def _enable(tmp_path: Path, *provider_ids: str) -> None:
    """Enabled-aware generic-LSP projection only targets enabled providers."""
    for provider_id in provider_ids:
        set_provider_enabled(tmp_path, provider_id, enabled=True)


class _Provider:
    def __init__(
        self,
        provider_id: str,
        *,
        native: bool,
        has_mcp: bool = True,
        receive_lsp_mcp: bool = True,
        declared_families: tuple[str, ...] = ("lsp-mcp-projection",),
    ) -> None:
        self.provider_id = provider_id
        self.mcp_config = object() if has_mcp else None
        self.language_servers_config = object() if native else None
        self.on_lsp_enabled = None
        self.receive_lsp_mcp = receive_lsp_mcp
        self._declared_families = declared_families

    def automation_capability(self, family_id: str) -> object | None:
        """Mirror ProviderDescriptor: participation requires a declaration."""
        return object() if family_id in self._declared_families else None


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def _register_lsp_descriptors() -> None:
    # Mirror what register_all_components() loads from the shipped coding-lsp
    # config: the implementation descriptors carry the generic-mcp projection
    # facts (A6/C3 moved these out of code into descriptor metadata), and the
    # bindings reference them by writer key.
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="ag-lsp",
            raw={
                "projection": {
                    "generic-mcp": {
                        "managed-id": "coding-lsp/ag-lsp",
                        "name": "ag-lsp",
                        "command": "package-python",
                        "args": ["-m", "audiagentic.components.coding_lsp.lsp_mcp"],
                        "env": {"PYTHONPATH": "package-src"},
                    }
                }
            },
        )
    )
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="blackwell-agent-lsp",
            raw={
                "projection": {
                    "generic-mcp": {
                        "managed-id": "coding-lsp/blackwell-agent-lsp",
                        "name": "blackwell-agent-lsp",
                        "command": "agent-lsp",
                        "args-from-runtime-servers": True,
                    }
                }
            },
        )
    )
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="blackwell-agent-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="blackwell-agent-lsp.mcp-args",
        )
    )


def test_sync_generic_lsp_routes_by_provider_capability(tmp_path: Path, monkeypatch) -> None:
    _register_lsp_descriptors()
    providers = {
        "codex": _Provider("codex", native=True),
        "claude": _Provider("claude", native=False),
        "aider": _Provider("aider", native=False, has_mcp=False),
    }
    _enable(tmp_path, "codex", "claude", "aider")
    captured: dict[str, dict] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured[provider_id] = desired_entries
        assert managed_ids == {"coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"}
        return {"ok": True}

    from audiagentic.components.providers.contracts.lsp_mcp_projection import (
        LspMcpProjectionEntry,
        LspMcpProjectionRequest,
    )
    from audiagentic.components.providers.services.lsp_mcp_projection import (
        manage_lsp_mcp_projection_all,
    )

    monkeypatch.setattr(
        "audiagentic.components.providers.descriptors.registry.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_mcp_projection.get_descriptor",
        lambda pid: providers.get(pid),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.feature_resolution.enabled_provider_ids",
        lambda root: set(providers.keys()),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="apply",
        request=LspMcpProjectionRequest(
            managed_ids=("coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"),
            entries=(LspMcpProjectionEntry(
                managed_id="coding-lsp/ag-lsp",
                name="ag-lsp",
                command="python",
            ),),
        ),
    )

    assert all(r.ok for r in results)
    # aider has no mcp_config — skipped by manage_lsp_mcp_projection_all
    assert all(r.provider_id != "aider" for r in results)
    # codex has both mcp_config and language_servers_config — should receive MCP
    assert "coding-lsp/ag-lsp" in captured["codex"]
    assert captured["codex"]["coding-lsp/ag-lsp"][0] == "ag-lsp"
    assert list(captured["claude"]) == ["coding-lsp/ag-lsp"]
    assert captured["claude"]["coding-lsp/ag-lsp"][0] == "ag-lsp"


def test_sync_generic_lsp_projects_blackwell_agent_lsp_when_active(tmp_path: Path, monkeypatch) -> None:
    _register_lsp_descriptors()
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "blackwell-agent-lsp",
        ImplementationState(enabled=True),
    )
    _enable(tmp_path, "claude")
    published: dict[str, Any] = {}

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.lsp_mcp_projection import (
            LspMcpProjectionResult,
        )
        published.update({
            "managed_ids": set(request.managed_ids),
            "entries": list(request.entries),
        })
        return [LspMcpProjectionResult(ok=True, provider_id="claude")]

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_lsp_mcp_projection_all",
        fake_manage_all,
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["ok"] is True
    assert [e.managed_id for e in published["entries"]] == ["coding-lsp/blackwell-agent-lsp"]


def test_sync_generic_lsp_projects_blackwell_agent_lsp_args(tmp_path: Path, monkeypatch) -> None:
    _register_lsp_descriptors()
    set_feature_state(tmp_path, "coding-lsp", "language", "python", FeatureState(enabled=True))
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "blackwell-agent-lsp",
        ImplementationState(enabled=True),
    )
    _enable(tmp_path, "claude")
    published: dict[str, Any] = {}

    def fake_manage_all(project_root, *, mode, request):
        from audiagentic.components.providers.contracts.lsp_mcp_projection import (
            LspMcpProjectionResult,
        )
        published.update({
            "managed_ids": set(request.managed_ids),
            "entries": list(request.entries),
        })
        return [LspMcpProjectionResult(ok=True, provider_id="claude")]

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_lsp_mcp_projection_all",
        fake_manage_all,
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["ok"] is True
    entry = published["entries"][0]
    assert entry.name == "blackwell-agent-lsp"
    assert entry.command == "agent-lsp"
    assert entry.args == ("python:pyright-langserver,--stdio",)


def test_prune_generic_lsp_only_targets_component_owned_entry(tmp_path: Path, monkeypatch) -> None:
    providers = {
        "codex": _Provider("codex", native=True),
        "claude": _Provider("claude", native=False),
    }
    captured: dict[str, set[str]] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured[provider_id] = managed_ids
        assert desired_entries == {}
        return {"ok": True}

    from audiagentic.components.providers.contracts.lsp_mcp_projection import (
        LspMcpProjectionRequest,
    )
    from audiagentic.components.providers.services.lsp_mcp_projection import (
        manage_lsp_mcp_projection_all,
    )

    monkeypatch.setattr(
        "audiagentic.components.providers.descriptors.registry.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_mcp_projection.get_descriptor",
        lambda pid: providers.get(pid),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.feature_resolution.enabled_provider_ids",
        lambda root: set(providers.keys()),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.lsp_mcp_projection.sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    results = manage_lsp_mcp_projection_all(
        tmp_path,
        mode="prune",
        request=LspMcpProjectionRequest(
            managed_ids=("coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"),
        ),
    )

    assert all(r.ok for r in results)
    assert captured == {
        "codex": {"coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"},
        "claude": {"coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"},
    }
