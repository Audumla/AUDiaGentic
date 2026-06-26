"""Tests for foundation/descriptors/loader.py"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.descriptors.loader import (
    DescriptorSpec,
    iter_descriptor_files,
    load_descriptor,
)


class TestDescriptorSpec:
    """Test descriptor field specification and loading."""

    def test_data_field(self) -> None:
        """Data field loads literal value."""
        spec = DescriptorSpec()
        spec.add("name", yaml_key="display_name", kind="data")
        result = spec.load({"display_name": "Test Provider"})
        assert result["name"] == "Test Provider"

    def test_ref_field(self) -> None:
        """Ref field resolves module:dotpath."""
        spec = DescriptorSpec()
        spec.add("reader_fn", yaml_key="reader", kind="ref")
        result = spec.load({"reader": "audiagentic.foundation.mcp.json_format:read_mcp_json"})
        assert callable(result["reader_fn"])

    def test_required_field_missing_raises(self) -> None:
        """Missing required field raises VAL-DESC-003."""
        spec = DescriptorSpec()
        spec.add("id", yaml_key="provider_id", kind="data", required=True)
        with pytest.raises(AudiaGenticError, match="VAL-DESC-003"):
            spec.load({})

    def test_optional_field_defaults(self) -> None:
        """Missing optional field uses default."""
        spec = DescriptorSpec()
        spec.add("url", yaml_key="url", kind="data", default="")
        result = spec.load({})
        assert result["url"] == ""

    def test_nested_field_with_builder(self) -> None:
        """Nested field uses builder function."""
        def build_permissions(data: dict) -> dict:
            return {"can_write": data.get("can_write_files", False)}

        spec = DescriptorSpec()
        spec.add("permissions", yaml_key="permissions", kind="nested", builder=build_permissions)
        result = spec.load({"permissions": {"can_write_files": True}})
        assert result["permissions"]["can_write"] is True

    def test_step_field(self) -> None:
        """Step field builds workflow step."""
        spec = DescriptorSpec()
        spec.add("install_step", yaml_key="install", kind="step")
        result = spec.load({
            "install": {
                "type": "shell",
                "id": "install",
                "command": ["npm", "install", "package"],
            }
        })
        from audiagentic.foundation.workflow.invocation.steps import ShellStep
        assert isinstance(result["install_step"], ShellStep)


class TestIterDescriptorFiles:
    """Test YAML file discovery."""

    def test_returns_yaml_files(self, tmp_path: Path) -> None:
        """Returns .yaml files."""
        (tmp_path / "a.yaml").write_text("key: value")
        files = iter_descriptor_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "a.yaml"

    def test_returns_yml_files(self, tmp_path: Path) -> None:
        """Returns .yml files."""
        (tmp_path / "a.yml").write_text("key: value")
        files = iter_descriptor_files(tmp_path)
        assert len(files) == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        files = iter_descriptor_files(tmp_path)
        assert files == []

    def test_nonexistent_directory(self) -> None:
        """Nonexistent directory returns empty list."""
        files = iter_descriptor_files(Path("/nonexistent/path"))
        assert files == []


class TestLoadDescriptor:
    """Test YAML file loading."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Load valid YAML file."""
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text("provider_id: test\nname: Test")
        spec = DescriptorSpec()
        spec.add("provider_id", yaml_key="provider_id", kind="data", required=True)
        spec.add("name", yaml_key="name", kind="data")
        result = load_descriptor(yaml_path, spec)
        assert result["provider_id"] == "test"
        assert result["name"] == "Test"

    def test_load_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """Invalid YAML raises VAL-DESC-003."""
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(": : :")
        spec = DescriptorSpec()
        with pytest.raises(AudiaGenticError, match="VAL-DESC-003"):
            load_descriptor(yaml_path, spec)

    def test_load_non_mapping_raises(self, tmp_path: Path) -> None:
        """YAML that is not a mapping raises VAL-DESC-003."""
        yaml_path = tmp_path / "list.yaml"
        yaml_path.write_text("- item1\n- item2")
        spec = DescriptorSpec()
        with pytest.raises(AudiaGenticError, match="VAL-DESC-003"):
            load_descriptor(yaml_path, spec)

    def test_constructor_builds_object(self, tmp_path: Path) -> None:
        """Constructor builds typed object."""
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class SimpleDescriptor:
            id: str
            name: str = ""

        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text("id: test\nname: Test")
        spec = DescriptorSpec(constructor=SimpleDescriptor)
        spec.add("id", yaml_key="id", kind="data", required=True)
        spec.add("name", yaml_key="name", kind="data", default="")
        result = load_descriptor(yaml_path, spec)
        assert isinstance(result, SimpleDescriptor)
        assert result.id == "test"
        assert result.name == "Test"
