"""Dev-only tests for the foundation component registry.

Exercises all registry operations against a real (tmp) filesystem.
Not collected by default — run explicitly:

    pytest tests/dev/

These tests mutate and delete files in tmp_path. Never run against a real project root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.loader import register_all_components

register_all_components()

from audiagentic.foundation.components import (
    all_descriptors,
    get_descriptor,
    get_owned_files,
    is_enabled,
    is_installed,
    uninstall_component,
)
from audiagentic.foundation.components.base import (
    MODE_CREATE_IF_MISSING,
    MODE_REQUIRED_MANAGED,
    MODE_RUNTIME_ONLY,
    ComponentDescriptor,
    ComponentFile,
)
from audiagentic.foundation.components.registry import register
from audiagentic.paths import SRC_ROOT as SRC

pytestmark = pytest.mark.dev


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_component_marker(root: Path, component_id: str, *, enabled: bool) -> None:
    import yaml
    marker_dir = root / ".audiagentic" / "components"
    marker_dir.mkdir(parents=True, exist_ok=True)
    data = {"component-id": component_id, "enabled": enabled, "version": "0.1.0"}
    (marker_dir / f"{component_id}.yaml").write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=True), encoding="utf-8"
    )


def _make_descriptor(component_id: str, *, files: tuple[ComponentFile, ...] = ()) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name=component_id,
        description="test component",
        detection_marker=f".audiagentic/test-markers/{component_id}",
        files=files,
    )


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------

def test_all_descriptors_returns_all_builtin_components() -> None:
    descs = all_descriptors()
    expected = {
        "core-lifecycle", "release-audit-ledger", "provider-layer",
        "planning", "agent-jobs", "discord-overlay", "optional-server",
    }
    assert expected.issubset(descs.keys())


def test_get_descriptor_returns_correct_descriptor() -> None:
    d = get_descriptor("core-lifecycle")
    assert d is not None
    assert d.component_id == "core-lifecycle"
    assert d.detection_marker == ".audiagentic/components/core-lifecycle.yaml"


def test_get_descriptor_returns_none_for_unknown() -> None:
    assert get_descriptor("nonexistent-xyz") is None


def test_register_custom_component() -> None:
    custom = _make_descriptor("test-custom-xyz")
    register(custom)
    assert get_descriptor("test-custom-xyz") is custom
    # Clean up — remove from registry after test
    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-custom-xyz", None)


# ---------------------------------------------------------------------------
# is_installed
# ---------------------------------------------------------------------------

def test_is_installed_true_when_marker_exists(tmp_path: Path) -> None:
    marker = tmp_path / ".audiagentic" / "components" / "core-lifecycle.yaml"
    marker.parent.mkdir(parents=True)
    marker.write_text("component-id: core-lifecycle\nenabled: true\n", encoding="utf-8")
    assert is_installed("core-lifecycle", tmp_path) is True


def test_is_installed_false_when_marker_missing(tmp_path: Path) -> None:
    assert is_installed("core-lifecycle", tmp_path) is False


def test_is_installed_false_for_unknown_component(tmp_path: Path) -> None:
    assert is_installed("nonexistent-xyz", tmp_path) is False


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------

def test_is_enabled_true_when_marker_missing(tmp_path: Path) -> None:
    assert is_enabled("core-lifecycle", tmp_path) is True


def test_is_enabled_true_when_explicitly_enabled(tmp_path: Path) -> None:
    _write_component_marker(tmp_path, "core-lifecycle", enabled=True)
    assert is_enabled("core-lifecycle", tmp_path) is True


def test_is_enabled_false_when_explicitly_disabled(tmp_path: Path) -> None:
    _write_component_marker(tmp_path, "core-lifecycle", enabled=False)
    assert is_enabled("core-lifecycle", tmp_path) is False


def test_is_enabled_true_when_other_component_marker_present(tmp_path: Path) -> None:
    _write_component_marker(tmp_path, "other-component", enabled=True)
    # core-lifecycle marker is absent — defaults to True
    assert is_enabled("core-lifecycle", tmp_path) is True


# ---------------------------------------------------------------------------
# get_owned_files
# ---------------------------------------------------------------------------

def test_get_owned_files_returns_existing_files(tmp_path: Path) -> None:
    # Create a descriptor with two files and register it
    f1 = tmp_path / "file-a.txt"
    f2 = tmp_path / "file-b.txt"
    f1.write_text("a", encoding="utf-8")
    # f2 intentionally not created

    desc = _make_descriptor("test-owned-xyz", files=(
        ComponentFile("file-a.txt", MODE_CREATE_IF_MISSING),
        ComponentFile("file-b.txt", MODE_CREATE_IF_MISSING),
    ))
    register(desc)

    owned = get_owned_files("test-owned-xyz", tmp_path)
    assert f1 in owned
    assert f2 not in owned

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-owned-xyz", None)


def test_get_owned_files_lifecycle_filter(tmp_path: Path) -> None:
    runtime_file = tmp_path / ".audiagentic" / "runtime" / "state.json"
    config_file = tmp_path / ".audiagentic" / "config" / "settings.yaml"
    runtime_file.parent.mkdir(parents=True)
    config_file.parent.mkdir(parents=True)
    runtime_file.write_text("{}", encoding="utf-8")
    config_file.write_text("x: 1", encoding="utf-8")

    desc = _make_descriptor("test-filter-xyz", files=(
        ComponentFile(".audiagentic/runtime/state.json", MODE_RUNTIME_ONLY),
        ComponentFile(".audiagentic/config/settings.yaml", MODE_CREATE_IF_MISSING),
    ))
    register(desc)

    runtime_only = get_owned_files("test-filter-xyz", tmp_path, lifecycle=MODE_RUNTIME_ONLY)
    assert runtime_file in runtime_only
    assert config_file not in runtime_only

    config_only = get_owned_files("test-filter-xyz", tmp_path, lifecycle=MODE_CREATE_IF_MISSING)
    assert config_file in config_only
    assert runtime_file not in config_only

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-filter-xyz", None)


def test_get_owned_files_recursive_dir(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".agents" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "one.md").write_text("skill1", encoding="utf-8")
    (skills_dir / "two.md").write_text("skill2", encoding="utf-8")

    desc = _make_descriptor("test-recursive-xyz", files=(
        ComponentFile(".agents/skills", MODE_REQUIRED_MANAGED, recursive=True),
    ))
    register(desc)

    owned = get_owned_files("test-recursive-xyz", tmp_path)
    assert skills_dir / "one.md" in owned
    assert skills_dir / "two.md" in owned

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-recursive-xyz", None)


# ---------------------------------------------------------------------------
# uninstall_component
# ---------------------------------------------------------------------------

def test_uninstall_removes_runtime_only_files(tmp_path: Path) -> None:
    runtime_file = tmp_path / ".audiagentic" / "runtime" / "cache.json"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("{}", encoding="utf-8")

    desc = _make_descriptor("test-uninstall-rt-xyz", files=(
        ComponentFile(".audiagentic/runtime/cache.json", MODE_RUNTIME_ONLY),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-rt-xyz", tmp_path)
    assert runtime_file in deleted
    assert not runtime_file.exists()

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-rt-xyz", None)


def test_uninstall_removes_required_managed_files(tmp_path: Path) -> None:
    managed_file = tmp_path / "CLAUDE.md"
    managed_file.write_text("instructions", encoding="utf-8")

    desc = _make_descriptor("test-uninstall-rm-xyz", files=(
        ComponentFile("CLAUDE.md", MODE_REQUIRED_MANAGED),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-rm-xyz", tmp_path)
    assert managed_file in deleted
    assert not managed_file.exists()

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-rm-xyz", None)


def test_uninstall_preserves_create_if_missing_without_flag(tmp_path: Path) -> None:
    config_file = tmp_path / ".audiagentic" / "config" / "project.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("x: 1", encoding="utf-8")

    desc = _make_descriptor("test-uninstall-cim-xyz", files=(
        ComponentFile(".audiagentic/config/project.yaml", MODE_CREATE_IF_MISSING),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-cim-xyz", tmp_path, remove_configs=False)
    assert config_file not in deleted
    assert config_file.exists()

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-cim-xyz", None)


def test_uninstall_removes_create_if_missing_with_flag(tmp_path: Path) -> None:
    config_file = tmp_path / ".audiagentic" / "config" / "project.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("x: 1", encoding="utf-8")

    desc = _make_descriptor("test-uninstall-cim2-xyz", files=(
        ComponentFile(".audiagentic/config/project.yaml", MODE_CREATE_IF_MISSING),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-cim2-xyz", tmp_path, remove_configs=True)
    assert config_file in deleted
    assert not config_file.exists()

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-cim2-xyz", None)


def test_uninstall_tolerates_missing_files(tmp_path: Path) -> None:
    desc = _make_descriptor("test-uninstall-missing-xyz", files=(
        ComponentFile(".audiagentic/runtime/nonexistent.json", MODE_RUNTIME_ONLY),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-missing-xyz", tmp_path)
    assert deleted == []

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-missing-xyz", None)


def test_uninstall_removes_recursive_dir(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".agents" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "skill.md").write_text("x", encoding="utf-8")

    desc = _make_descriptor("test-uninstall-rec-xyz", files=(
        ComponentFile(".agents/skills", MODE_REQUIRED_MANAGED, recursive=True),
    ))
    register(desc)

    deleted = uninstall_component("test-uninstall-rec-xyz", tmp_path)
    assert skills_dir in deleted
    assert not skills_dir.exists()

    from audiagentic.foundation.components import registry as _reg
    _reg._registry.pop("test-uninstall-rec-xyz", None)


def test_uninstall_returns_empty_list_for_unknown_component(tmp_path: Path) -> None:
    assert uninstall_component("nonexistent-xyz", tmp_path) == []


# ---------------------------------------------------------------------------
# Layer integrity
# ---------------------------------------------------------------------------

def test_foundation_components_base_has_no_runtime_imports() -> None:
    import ast
    base_path = SRC / "audiagentic" / "foundation" / "components" / "base.py"
    tree = ast.parse(base_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("audiagentic.runtime"), (
                f"foundation/components/base.py must not import from runtime: {node.module}"
            )


def test_mode_constants_are_same_object_in_baseline_sync() -> None:
    from audiagentic.foundation.components.base import MODE_CREATE_IF_MISSING as FC
    from audiagentic.runtime.lifecycle.baseline_sync import MODE_CREATE_IF_MISSING as BS
    assert FC == BS, "MODE_* constants must be identical between foundation and baseline_sync"
