"""Tests for foundation/paths/component_paths.py (AR05) and
resolve_active_implementation (AR15)."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths import load_component_paths, resolve_component_path

_DEFAULTS = {"data-dir": "docs/data", "index": "docs/data/index.md"}


def test_defaults_used_when_nothing_installed(tmp_path: Path):
    assert resolve_component_path(tmp_path, "sample", "data-dir", _DEFAULTS) == tmp_path / "docs/data"
    assert load_component_paths(tmp_path, "sample", _DEFAULTS) == _DEFAULTS


def test_component_config_paths_override_defaults(tmp_path: Path):
    marker = tmp_path / ".audiagentic" / "components" / "sample.yaml"
    marker.parent.mkdir(parents=True)
    marker.write_text("paths:\n  data-dir: custom/data\n", encoding="utf-8")

    assert resolve_component_path(tmp_path, "sample", "data-dir", _DEFAULTS) == tmp_path / "custom/data"
    # Key absent from config falls back to defaults.
    assert resolve_component_path(tmp_path, "sample", "index", _DEFAULTS) == tmp_path / "docs/data/index.md"


def test_undefined_key_raises_val_paths_001(tmp_path: Path):
    with pytest.raises(AudiaGenticError, match="VAL-PATHS-001"):
        resolve_component_path(tmp_path, "sample", "nonexistent-key", _DEFAULTS)


def test_planning_paths_resolve_via_implementation_descriptor(tmp_path: Path):
    """Planning's paths come from the implementation descriptor when registered."""
    from audiagentic.components.planning import planning_paths
    from audiagentic.foundation.components.loader import register_all_components

    register_all_components()
    active = planning_paths.plans_active_dir(tmp_path)
    assert active == tmp_path / "docs" / "planning" / "active"


def test_resolve_active_implementation_fallback(tmp_path: Path):
    from audiagentic.foundation.features.registry import resolve_active_implementation

    assert resolve_active_implementation(tmp_path, "no-such-component", fallback="x") == "x"
    assert resolve_active_implementation(tmp_path, "no-such-component") is None
