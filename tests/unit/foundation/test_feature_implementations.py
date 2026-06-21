from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_descriptor
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features import registry
from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.loader import register_from_yaml
from audiagentic.foundation.features.resolver import resolve_implementation
from audiagentic.foundation.features.state import get_implementation_state


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def setup_function() -> None:
    registry.clear()


def teardown_function() -> None:
    registry.clear()


def test_load_implementation_descriptor_from_yaml(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "agent-lsp.yaml",
        """
type: implementation
parent: coding-lsp
id: agent-lsp
display-name: Agent LSP
dependencies:
  agent-lsp:
    probe: binary:agent-lsp
options-schema:
  warm-runtime:
    type: bool
    default: true
""".strip(),
    )

    descriptor = register_from_yaml(path)

    assert descriptor.parent == "coding-lsp"
    assert descriptor.implementation_id == "agent-lsp"
    assert descriptor.dependencies["agent-lsp"]["probe"] == "binary:agent-lsp"
    assert registry.get_implementation("coding-lsp", "agent-lsp") == descriptor


def test_load_binding_descriptor_from_yaml(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "agent-lsp.python.yaml",
        """
type: binding
parent: coding-lsp
implementation: agent-lsp
feature-kind: language
feature: python
uses-dependencies:
  - feature.language.python.pyright
projection:
  writer-key: agent-lsp.python
options-schema:
  server-profile:
    type: enum
    values: [pyright, basedpyright]
    default: pyright
""".strip(),
    )

    descriptor = register_from_yaml(path)

    assert descriptor.parent == "coding-lsp"
    assert descriptor.implementation == "agent-lsp"
    assert descriptor.feature_kind == "language"
    assert descriptor.feature == "python"
    assert descriptor.uses_dependencies == ("feature.language.python.pyright",)
    assert descriptor.projection_writer_key == "agent-lsp.python"
    assert registry.get_binding("coding-lsp", "agent-lsp", "language", "python") == descriptor


def test_binding_descriptor_requires_feature_kind(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "agent-lsp.python.yaml",
        """
type: binding
parent: coding-lsp
implementation: agent-lsp
feature: python
""".strip(),
    )

    try:
        register_from_yaml(path)
    except AudiaGenticError as exc:
        assert exc.code == "VAL-FDESC-001"
        assert exc.kind == "feature-descriptors"
        assert exc.details["field"] == "feature-kind"
    else:
        raise AssertionError("missing feature-kind should fail")


def test_binding_writer_registry_resolves_by_parent_and_key() -> None:
    def _writer(project_root: Path) -> dict[str, object]:
        return {"root": project_root}

    registry.register_binding_writer("coding-lsp", "agent-lsp.mcp-args", _writer)

    assert registry.get_binding_writer("coding-lsp", "agent-lsp.mcp-args") is _writer
    assert registry.get_binding_writer("other", "agent-lsp.mcp-args") is None


def test_binding_writer_registry_separates_projection_kind() -> None:
    def _mcp_writer(project_root: Path) -> dict[str, object]:
        return {"mcp": project_root}

    def _language_server_writer(project_root: Path, feature: str) -> dict[str, object]:
        return {feature: project_root}

    registry.register_binding_writer(
        "coding-lsp",
        "coding-lsp.lsp-json",
        _mcp_writer,
        projection_kind="generic-mcp",
    )
    registry.register_binding_writer(
        "coding-lsp",
        "coding-lsp.lsp-json",
        _language_server_writer,
        projection_kind="language-server",
    )

    assert registry.get_binding_writer(
        "coding-lsp", "coding-lsp.lsp-json", projection_kind="generic-mcp"
    ) is _mcp_writer
    assert registry.get_binding_writer(
        "coding-lsp", "coding-lsp.lsp-json", projection_kind="language-server"
    ) is _language_server_writer


def test_register_all_components_dispatches_implementation_and_binding_yaml(tmp_path: Path) -> None:
    _write(
        tmp_path / "coding-lsp.yaml",
        """
type: component
id: coding-lsp
display-name: Coding LSP
description: LSP
detection-marker: .audiagentic/components/coding-lsp.yaml
implementation-cardinality: exclusive
""".strip(),
    )
    _write(
        tmp_path / "agent-lsp.yaml",
        """
type: implementation
parent: coding-lsp
id: agent-lsp
""".strip(),
    )
    _write(
        tmp_path / "agent-lsp.python.yaml",
        """
type: binding
parent: coding-lsp
implementation: agent-lsp
feature-kind: language
feature: python
""".strip(),
    )

    descriptors = register_all_components([tmp_path])

    assert [descriptor.component_id for descriptor in descriptors] == ["coding-lsp"]
    assert get_descriptor("coding-lsp").implementation_cardinality == "exclusive"
    assert registry.get_implementation("coding-lsp", "agent-lsp") is not None
    assert registry.get_binding("coding-lsp", "agent-lsp", "language", "python") is not None


def test_exclusive_implementation_enable_disables_previous_active(tmp_path: Path) -> None:
    register_all_components([
        _write(
            tmp_path / "config" / "coding-lsp.yaml",
            """
type: component
id: coding-lsp
display-name: Coding LSP
description: LSP
detection-marker: .audiagentic/components/coding-lsp.yaml
implementation-cardinality: exclusive
""".strip(),
        ).parent
    ])
    register_from_yaml(_write(tmp_path / "ag-lsp.yaml", "type: implementation\nparent: coding-lsp\nid: ag-lsp\n"))
    agent = register_from_yaml(
        _write(
            tmp_path / "agent-lsp.yaml",
            """
type: implementation
parent: coding-lsp
id: agent-lsp
options-schema:
  warm-runtime:
    type: bool
    default: true
""".strip(),
        )
    )

    assert enable_implementation(tmp_path, "coding-lsp", "ag-lsp")["ok"] is True
    assert enable_implementation(tmp_path, "coding-lsp", "agent-lsp")["ok"] is True

    assert get_implementation_state(tmp_path, "coding-lsp", "ag-lsp").enabled is False
    assert get_implementation_state(tmp_path, "coding-lsp", "agent-lsp").enabled is True
    assert resolve_implementation(tmp_path, agent).effective_options == {"warm-runtime": True}


def test_multi_implementation_enable_keeps_existing_active(tmp_path: Path) -> None:
    register_all_components([
        _write(
            tmp_path / "config" / "providers.yaml",
            """
type: component
id: providers
display-name: Providers
description: Providers
detection-marker: .audiagentic/components/providers.yaml
implementation-cardinality: multi
""".strip(),
        ).parent
    ])
    register_from_yaml(_write(tmp_path / "codex.yaml", "type: implementation\nparent: providers\nid: codex\n"))
    register_from_yaml(_write(tmp_path / "claude.yaml", "type: implementation\nparent: providers\nid: claude\n"))

    assert enable_implementation(tmp_path, "providers", "codex")["ok"] is True
    result = enable_implementation(tmp_path, "providers", "claude")

    assert result["ok"] is True
    assert result["cardinality"] == "multi"
    assert get_implementation_state(tmp_path, "providers", "codex").enabled is True
    assert get_implementation_state(tmp_path, "providers", "claude").enabled is True
