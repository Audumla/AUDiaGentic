from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.coding_lsp.runtime_resolver import (
    active_language_bindings,
    active_lsp_implementation,
    resolve_active_runtime_servers,
)
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationState,
)
from audiagentic.foundation.features.state import (
    set_feature_state,
    set_implementation_state,
)


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def _register_language_bindings() -> None:
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
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="agent-lsp",
            feature_kind="language",
            feature="rust",
            projection_writer_key="agent-lsp.mcp-args",
        )
    )


def test_active_lsp_implementation_defaults_to_ag_lsp(tmp_path: Path) -> None:
    assert active_lsp_implementation(tmp_path) == "ag-lsp"


def test_resolve_active_runtime_servers_uses_enabled_shared_languages(tmp_path: Path) -> None:
    _register_language_bindings()
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        FeatureState(enabled=True),
    )

    servers = resolve_active_runtime_servers(tmp_path)

    assert list(servers) == ["python"]
    assert servers["python"].command == ["pyright-langserver", "--stdio"]
    assert ".py" in servers["python"].file_extensions


def test_resolve_active_runtime_servers_filters_by_active_implementation_binding(tmp_path: Path) -> None:
    _register_language_bindings()
    set_implementation_state(
        tmp_path,
        "coding-lsp",
        "agent-lsp",
        ImplementationState(enabled=True),
    )
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        "rust",
        FeatureState(enabled=True),
    )

    bindings = active_language_bindings(tmp_path)
    servers = resolve_active_runtime_servers(tmp_path)

    assert [binding.feature for binding in bindings] == ["rust"]
    assert list(servers) == ["rust"]
    assert servers["rust"].command == ["rust-analyzer"]


def test_resolve_active_runtime_servers_applies_language_feature_options(tmp_path: Path) -> None:
    _register_language_bindings()
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        FeatureState(
            enabled=True,
            options={"server-settings": {"python.analysis.typeCheckingMode": "strict"}},
        ),
    )

    servers = resolve_active_runtime_servers(tmp_path)

    assert servers["python"].settings == {"python.analysis.typeCheckingMode": "strict"}
