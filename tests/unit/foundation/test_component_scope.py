"""Unit tests for component scope dispatch (project vs harness)."""
from __future__ import annotations

from unittest.mock import patch

from audiagentic.foundation.components.base import (
    SCOPE_HARNESS,
    SCOPE_PROJECT,
    ComponentDescriptor,
)
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import (
    component_root,
    is_enabled,
    is_installed,
    marker_path,
    register,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _project_desc(component_id: str = "test-project-comp") -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name="Test Project",
        description="",
        detection_marker=f".audiagentic/components/{component_id}.yaml",
        scope=SCOPE_PROJECT,
    )


def _harness_desc(component_id: str = "test-harness-comp") -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name="Test Harness",
        description="",
        detection_marker=f"components/{component_id}.yaml",
        scope=SCOPE_HARNESS,
    )


# ── component_root dispatch ───────────────────────────────────────────────────

def test_project_scope_root_is_project_root(tmp_path):
    desc = _project_desc()
    assert component_root(desc, tmp_path) == tmp_path


def test_harness_scope_root_is_audiagentic_home(tmp_path):
    desc = _harness_desc()
    fake_home = tmp_path / "fake_home"
    with patch("audiagentic.foundation.components.registry.audiagentic_home", return_value=fake_home):
        result = component_root(desc, tmp_path / "some_project")
    assert result == fake_home


def test_harness_root_independent_of_project_root(tmp_path):
    desc = _harness_desc()
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    fake_home = tmp_path / "harness_home"
    with patch("audiagentic.foundation.components.registry.audiagentic_home", return_value=fake_home):
        assert component_root(desc, project_a) == component_root(desc, project_b)


# ── marker_path structure ─────────────────────────────────────────────────────

def test_project_marker_path_has_dot_audiagentic(tmp_path):
    p = marker_path("my-comp", tmp_path, SCOPE_PROJECT)
    assert p == tmp_path / ".audiagentic" / "components" / "my-comp.yaml"


def test_harness_marker_path_no_dot_audiagentic(tmp_path):
    p = marker_path("auto-update", tmp_path, SCOPE_HARNESS)
    assert p == tmp_path / "components" / "auto-update.yaml"


# ── is_installed / is_enabled with scope ─────────────────────────────────────

def test_is_installed_project_scope(tmp_path):
    desc = _project_desc("proj-x")
    register(desc)
    assert not is_installed("proj-x", tmp_path)
    marker = tmp_path / ".audiagentic" / "components" / "proj-x.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("component-id: proj-x\nenabled: true\n")
    assert is_installed("proj-x", tmp_path)


def test_is_installed_harness_scope(tmp_path):
    desc = _harness_desc("harness-x")
    register(desc)
    fake_home = tmp_path / "harness_home"
    with patch("audiagentic.foundation.components.registry.audiagentic_home", return_value=fake_home):
        assert not is_installed("harness-x", tmp_path / "any_project")
        marker = fake_home / "components" / "harness-x.yaml"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("component-id: harness-x\nenabled: true\n")
        assert is_installed("harness-x", tmp_path / "any_project")


def test_is_enabled_harness_reads_from_harness_home(tmp_path):
    desc = _harness_desc("harness-y")
    register(desc)
    fake_home = tmp_path / "harness_home"
    marker = fake_home / "components" / "harness-y.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("component-id: harness-y\nenabled: false\n")
    with patch("audiagentic.foundation.components.registry.audiagentic_home", return_value=fake_home):
        assert not is_enabled("harness-y", tmp_path / "any_project")


# ── auto-update descriptor is registered with harness scope ──────────────────

def test_auto_update_registered_as_harness():
    register_all_components()
    from audiagentic.foundation.components.registry import get_descriptor
    desc = get_descriptor("auto-update")
    assert desc is not None
    assert desc.scope == SCOPE_HARNESS


def test_all_other_builtins_are_project_scope():
    register_all_components()
    from audiagentic.foundation.components.registry import all_descriptors
    project_scoped = {
        cid for cid, d in all_descriptors().items()
        if d.scope == SCOPE_PROJECT
    }
    for expected in ("core-lifecycle", "agent-jobs", "planning", "provider-layer"):
        assert expected in project_scoped
