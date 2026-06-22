from __future__ import annotations

from pathlib import Path

from audiagentic.components.coding_lsp.language_servers_sync import (
    sync_generic_lsp_mcp_to_providers,
)
from audiagentic.components.providers.services import lsp_projection
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
    ImplementationState,
)
from audiagentic.foundation.features.state import set_feature_state, set_implementation_state
from audiagentic.foundation.mcp import McpServerEntry


def _enable(tmp_path: Path, *provider_ids: str) -> None:
    """Enabled-aware generic-LSP projection only targets enabled providers."""
    for provider_id in provider_ids:
        set_provider_enabled(tmp_path, provider_id, enabled=True)


class _Provider:
    def __init__(self, provider_id: str, *, native: bool, has_mcp: bool = True, receive_lsp_mcp: bool = True) -> None:
        self.provider_id = provider_id
        self.mcp_config = object() if has_mcp else None
        self.language_servers_config = object() if native else None
        self.on_lsp_enabled = None
        self.receive_lsp_mcp = receive_lsp_mcp


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
            implementation_id="agent-lsp",
            raw={
                "projection": {
                    "generic-mcp": {
                        "managed-id": "coding-lsp/agent-lsp",
                        "name": "agent-lsp",
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
            implementation="agent-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="agent-lsp.mcp-args",
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
    captured: dict[str, dict[str, tuple[str, McpServerEntry]]] = {}

    def _fake_sync(*, provider_id, project_root, desired_entries, managed_ids):
        captured[provider_id] = desired_entries
        assert managed_ids == {"coding-lsp/ag-lsp", "coding-lsp/agent-lsp"}
        return {"ok": True}

    monkeypatch.setattr(
        lsp_projection,
        "all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        lsp_projection,
        "sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    result = lsp_projection.sync_generic_lsp_mcp_to_provider_configs(
        tmp_path,
        {"coding-lsp/ag-lsp": ("ag-lsp", McpServerEntry(name="ag-lsp", command="python"))},
        {"coding-lsp/ag-lsp", "coding-lsp/agent-lsp"},
    )

    assert result["ok"] is True
    assert "aider" in result["skipped"]
    assert captured["codex"] == {}
    assert list(captured["claude"]) == ["coding-lsp/ag-lsp"]
    assert captured["claude"]["coding-lsp/ag-lsp"][0] == "ag-lsp"


def test_sync_generic_lsp_projects_agent_lsp_when_active(tmp_path: Path, monkeypatch) -> None:
    _register_lsp_descriptors()
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "agent-lsp",
        ImplementationState(enabled=True),
    )
    _enable(tmp_path, "claude")
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {"ok": True, "synced": ["claude"]},
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["ok"] is True
    assert list(published["desired_entries"]) == ["coding-lsp/agent-lsp"]


def test_sync_generic_lsp_projects_agent_lsp_args(tmp_path: Path, monkeypatch) -> None:
    _register_lsp_descriptors()
    set_feature_state(tmp_path, "coding-lsp", "language", "python", FeatureState(enabled=True))
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "agent-lsp",
        ImplementationState(enabled=True),
    )
    _enable(tmp_path, "claude")
    published: dict[str, object] = {}
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.language_servers_sync._publish_provider_projection",
        lambda root, **payload: published.update(payload) or {"ok": True, "synced": ["claude"]},
    )

    result = sync_generic_lsp_mcp_to_providers(tmp_path)

    assert result["ok"] is True
    name, entry = published["desired_entries"]["coding-lsp/agent-lsp"]
    assert name == "agent-lsp"
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

    monkeypatch.setattr(
        lsp_projection,
        "all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        lsp_projection,
        "sync_managed_provider_mcp_subset",
        _fake_sync,
    )

    result = lsp_projection.prune_generic_lsp_mcp_from_provider_configs(
        tmp_path,
        {"coding-lsp/ag-lsp", "coding-lsp/agent-lsp"},
    )

    assert result["ok"] is True
    assert captured == {
        "codex": {"coding-lsp/ag-lsp", "coding-lsp/agent-lsp"},
        "claude": {"coding-lsp/ag-lsp", "coding-lsp/agent-lsp"},
    }
