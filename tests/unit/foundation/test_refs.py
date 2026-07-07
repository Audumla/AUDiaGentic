"""Tests for foundation/refs.py"""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.refs import resolve_ref


class TestResolveRef:
    """Test dotpath reference resolution."""

    def test_resolve_existing_function(self) -> None:
        """Resolve a known function by module:dotpath."""
        fn = resolve_ref("audiagentic.foundation.mcp.json_format:read_mcp_json")
        assert callable(fn)

    def test_resolve_existing_class(self) -> None:
        """Resolve a known class."""
        cls = resolve_ref("audiagentic.foundation.workflow.invocation.steps:ShellStep")
        assert cls.__name__ == "ShellStep"

    def test_resolve_nested_colon(self) -> None:
        """Resolve nested module path with additional colons."""
        obj = resolve_ref("audiagentic.foundation.mcp:json_format:read_mcp_json")
        assert callable(obj)

    def test_missing_module_raises(self) -> None:
        """Missing module raises VAL-DESC-001."""
        with pytest.raises(AudiaGenticError, match="VAL-DESC-001"):
            resolve_ref("nonexistent.module:func")

    def test_missing_attribute_raises(self) -> None:
        """Missing attribute raises VAL-DESC-001."""
        with pytest.raises(AudiaGenticError, match="VAL-DESC-001"):
            resolve_ref("audiagentic.foundation.mcp.json_format:nonexistent_func")

    def test_empty_string_raises(self) -> None:
        """Empty string raises VAL-DESC-001."""
        with pytest.raises(AudiaGenticError, match="VAL-DESC-001"):
            resolve_ref("")

    def test_no_colon_raises(self) -> None:
        """String without colon raises VAL-DESC-001."""
        with pytest.raises(AudiaGenticError, match="VAL-DESC-001"):
            resolve_ref("justamodule")
