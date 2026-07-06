from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.base import ComponentDescriptor
from audiagentic.foundation.components.loader import (
    _validate_descriptors_data,
    register_from_yaml,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _write_component(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _descriptor(component_id: str, *, depends_on: tuple[str, ...] = ()) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name=component_id,
        description="",
        detection_marker=f".audiagentic/components/{component_id}.yaml",
        depends_on=depends_on,
    )


def test_component_descriptor_requires_id(tmp_path: Path) -> None:
    path = tmp_path / "missing-id.yaml"
    _write_component(path, "type: component\ncontract-version: v1\n")

    with pytest.raises(AudiaGenticError, match="missing or empty id"):
        register_from_yaml(path)


def test_loaded_components_reject_duplicate_ids() -> None:
    layer = "/base/components"
    with pytest.raises(AudiaGenticError, match="duplicate component ids"):
        _validate_descriptors_data([(_descriptor("one"), layer), (_descriptor("one"), layer)])


def test_loaded_components_reject_unknown_dependency() -> None:
    layer = "/base/components"
    with pytest.raises(AudiaGenticError, match="depends on unknown component"):
        _validate_descriptors_data([(_descriptor("one", depends_on=("missing",)), layer)])


def test_default_detection_marker_project_scope(tmp_path: Path) -> None:
    path = tmp_path / "no-marker.yaml"
    _write_component(path, "type: component\ncontract-version: v1\nid: my-comp\n")

    desc = register_from_yaml(path)
    assert desc.detection_marker == ".audiagentic/components/my-comp.yaml"


def test_default_detection_marker_harness_scope(tmp_path: Path) -> None:
    path = tmp_path / "harness-no-marker.yaml"
    _write_component(path, "type: component\ncontract-version: v1\nid: my-harness\nscope: harness\n")

    desc = register_from_yaml(path)
    assert desc.detection_marker == "components/my-harness.yaml"


def test_explicit_detection_marker_preserved(tmp_path: Path) -> None:
    path = tmp_path / "explicit-marker.yaml"
    _write_component(path, "type: component\ncontract-version: v1\nid: my-explicit\ndetection-marker: custom/path.yaml\n")

    desc = register_from_yaml(path)
    assert desc.detection_marker == "custom/path.yaml"


def test_default_marker_file_synthesized(tmp_path: Path) -> None:
    path = tmp_path / "no-files.yaml"
    _write_component(path, "type: component\ncontract-version: v1\nid: my-no-files\n")

    desc = register_from_yaml(path)
    marker_files = [f for f in desc.files if f.rel_path == ".audiagentic/components/my-no-files.yaml"]
    assert len(marker_files) == 1
    assert marker_files[0].lifecycle == "create-if-missing"
    assert marker_files[0].description == "Installation marker"


def test_explicit_marker_file_not_duplicated(tmp_path: Path) -> None:
    path = tmp_path / "explicit-files.yaml"
    _write_component(path, "type: component\ncontract-version: v1\nid: my-explicit-files\ndetection-marker: custom.yaml\nfiles:\n  - path: custom.yaml\n    lifecycle: create-if-missing\n    description: Custom marker\n")

    desc = register_from_yaml(path)
    marker_files = [f for f in desc.files if f.rel_path == "custom.yaml"]
    assert len(marker_files) == 1


def test_no_derived_tool_catalog_without_explicit_harness_instructions(tmp_path: Path) -> None:
    """Per-tool definitions are component-owned and advertised over MCP; the
    loader never derives a consolidated tool catalog into the system prompt."""
    path = tmp_path / "with-tools.yaml"
    _write_component(path, """type: component
contract-version: v1
id: tool-comp
mcp-servers:
  - name: ag-tools
    module: test.mod
    direct-tools: [do_thing, list_thing]
    tool-descriptions:
      do_thing: Does a thing.
      list_thing: Lists things.
""")

    desc = register_from_yaml(path)
    assert desc.harness_instructions == ()


def test_explicit_harness_instructions_are_preserved(tmp_path: Path) -> None:
    """Components inject doctrine only by supplying an explicit section."""
    path = tmp_path / "explicit.yaml"
    _write_component(path, """type: component
contract-version: v1
id: explicit-comp
mcp-servers:
  - name: ag-srv
    module: test.mod
    direct-tools: [tool_a]
harness-instructions:
  - section: "Available components"
    content: |
      Doctrine that lands in a real template section.
""")

    desc = register_from_yaml(path)
    assert len(desc.harness_instructions) == 1
    assert desc.harness_instructions[0].section == "Available components"
