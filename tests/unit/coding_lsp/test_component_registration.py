from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components, register_from_yaml
from audiagentic.foundation.features import registry as feature_registry


def _coding_lsp_yaml_path() -> Path:
    return Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components" / "coding-lsp.yaml"


def _config_dir() -> Path:
    return _coding_lsp_yaml_path().parent


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def test_coding_lsp_yaml_loads() -> None:
    path = _coding_lsp_yaml_path()
    assert path.exists(), f"coding-lsp.yaml not found at {path}"
    descriptor = register_from_yaml(path)
    assert descriptor.component_id == "coding-lsp"
    assert descriptor.display_name == "Coding LSP"
    assert descriptor.implementation_cardinality == "exclusive"
    assert len(descriptor.mcp_servers) == 2
    names = {s.name for s in descriptor.mcp_servers}
    assert "ag-lsp-mgmt" in names
    assert "ag-lsp" in names


def test_coding_lsp_has_lifecycle_observer() -> None:
    path = _coding_lsp_yaml_path()
    descriptor = register_from_yaml(path)
    assert descriptor.lifecycle_observer == "audiagentic.components.coding_lsp.coding_lsp_bootstrap"


def test_coding_lsp_has_detection_marker() -> None:
    path = _coding_lsp_yaml_path()
    descriptor = register_from_yaml(path)
    assert descriptor.detection_marker == ".audiagentic/components/coding-lsp.yaml"


def test_coding_lsp_registers_nested_implementation_and_language_features() -> None:
    register_all_components([_config_dir()])

    assert feature_registry.get_implementation("coding-lsp", "ag-lsp") is not None
    agent_lsp = feature_registry.get_implementation("coding-lsp", "agent-lsp")
    assert agent_lsp is not None
    assert agent_lsp.dependencies["agent-lsp"]["probe"] == "binary:agent-lsp"
    python = feature_registry.get_feature("coding-lsp", "language", "python")
    assert python is not None
    assert python.dependencies["pyright"]["probe"] == "binary:pyright-langserver"


def test_coding_lsp_registers_ag_lsp_language_bindings() -> None:
    register_all_components([_config_dir()])

    bindings = feature_registry.get_bindings("coding-lsp")

    assert {
        key for key in bindings
        if key[0] == "ag-lsp" and key[1] == "language"
    } == {
        ("ag-lsp", "language", "cpp"),
        ("ag-lsp", "language", "python"),
        ("ag-lsp", "language", "python-ruff"),
        ("ag-lsp", "language", "rust"),
        ("ag-lsp", "language", "typescript"),
    }
    assert bindings[("ag-lsp", "language", "python")].uses_dependencies == ("pyright",)
    assert bindings[("ag-lsp", "language", "python")].projection_writer_key == "coding-lsp.lsp-json"
    assert bindings[("ag-lsp", "language", "python-ruff")].uses_dependencies == ("ruff",)
    assert bindings[("ag-lsp", "language", "python-ruff")].projection_writer_key == "coding-lsp.lsp-json"
    assert bindings[("agent-lsp", "language", "python")].uses_dependencies == ("agent-lsp", "pyright")
    assert bindings[("agent-lsp", "language", "python")].projection_writer_key == "agent-lsp.mcp-args"
