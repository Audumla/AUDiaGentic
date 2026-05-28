from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.loader import register_from_yaml


def _coding_lsp_yaml_path() -> Path:
    return Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components" / "optional" / "coding-lsp.yaml"


def test_coding_lsp_yaml_loads() -> None:
    path = _coding_lsp_yaml_path()
    assert path.exists(), f"coding-lsp.yaml not found at {path}"
    descriptor = register_from_yaml(path)
    assert descriptor.component_id == "coding-lsp"
    assert descriptor.display_name == "Coding LSP"
    assert len(descriptor.mcp_servers) == 2
    names = {s.name for s in descriptor.mcp_servers}
    assert "lsp-config-mcp" in names
    assert "lsp-mcp" in names


def test_coding_lsp_has_lifecycle_observer() -> None:
    path = _coding_lsp_yaml_path()
    descriptor = register_from_yaml(path)
    assert descriptor.lifecycle_observer == "audiagentic.components.optional.coding_lsp.bootstrap"


def test_coding_lsp_has_detection_marker() -> None:
    path = _coding_lsp_yaml_path()
    descriptor = register_from_yaml(path)
    assert descriptor.detection_marker == ".audiagentic/components/coding-lsp.yaml"
