"""Integration tests: component lifecycle — install, surface validation, disable, enable, uninstall.

Runs inside Docker (AUDIAGENTIC_DOCKER_TESTS=1). Each test exercises the full lifecycle of every
registered component: install → verify surface → disable → verify disabled → enable → uninstall →
verify cleanup. Components are discovered dynamically from the registry so new components are
automatically covered.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.helpers import sandbox as sandbox_helper

from audiagentic.foundation.components.base import MODE_CREATE_IF_MISSING, MODE_REQUIRED_MANAGED
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed
from audiagentic.runtime.lifecycle.components import (
    disable_component,
    enable_component,
    install_component,
    uninstall_component,
)


@pytest.fixture(scope="module", autouse=True)
def _register_components():
    register_all_components()


def _component_ids() -> list[str]:
    return sorted(all_descriptors().keys())


def _install_with_deps(component_id: str, project_root: Path) -> None:
    descriptor = all_descriptors()[component_id]
    for dep in descriptor.depends_on:
        if not is_installed(dep, project_root):
            _install_with_deps(dep, project_root)
    if not is_installed(component_id, project_root):
        result = install_component(component_id, project_root)
        assert result.get("ok") is True, f"install failed for {component_id}: {result}"


# ---------------------------------------------------------------------------
# Install: marker + declared files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("component_id", _component_ids())
def test_install_writes_marker(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"install-marker-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)

        marker = sb.repo / ".audiagentic" / "components" / f"{component_id}.yaml"
        assert marker.is_file(), f"marker missing after install: {marker}"

        data = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
        assert data.get("component-id") == component_id
        assert data.get("enabled") is True
        assert "installed-at" in data
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_install_sets_is_installed(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"install-state-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_install_creates_required_managed_files(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"install-files-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        descriptor = all_descriptors()[component_id]
        for cf in descriptor.files:
            if cf.lifecycle == MODE_REQUIRED_MANAGED and not cf.recursive:
                target = sb.repo / cf.rel_path
                assert target.is_file(), f"{component_id}: required-managed file missing: {cf.rel_path}"
    finally:
        sb.cleanup()


# ---------------------------------------------------------------------------
# Disable / Enable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("component_id", _component_ids())
def test_disable_sets_enabled_false(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"disable-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        result = disable_component(component_id, sb.repo)
        assert result.get("ok") is True
        assert not is_enabled(component_id, sb.repo)

        marker = sb.repo / ".audiagentic" / "components" / f"{component_id}.yaml"
        data = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
        assert data.get("enabled") is False
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_disable_does_not_remove_files(component_id: str, tmp_path: Path) -> None:
    """Disable is state-only — declared files must still exist."""
    sb = sandbox_helper.create(tmp_path, f"disable-files-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        disable_component(component_id, sb.repo)
        descriptor = all_descriptors()[component_id]
        for cf in descriptor.files:
            if cf.lifecycle == MODE_REQUIRED_MANAGED and not cf.recursive:
                target = sb.repo / cf.rel_path
                assert target.is_file(), f"{component_id}: file disappeared after disable: {cf.rel_path}"
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_enable_after_disable(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"enable-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        disable_component(component_id, sb.repo)
        assert not is_enabled(component_id, sb.repo)

        result = enable_component(component_id, sb.repo)
        assert result.get("ok") is True
        assert is_enabled(component_id, sb.repo)

        marker = sb.repo / ".audiagentic" / "components" / f"{component_id}.yaml"
        data = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
        assert data.get("enabled") is True
    finally:
        sb.cleanup()


# ---------------------------------------------------------------------------
# Uninstall: marker gone, managed files gone, configs preserved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("component_id", _component_ids())
def test_uninstall_removes_marker(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"uninstall-marker-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        marker = sb.repo / ".audiagentic" / "components" / f"{component_id}.yaml"
        assert marker.is_file()

        uninstall_component(component_id, sb.repo)

        assert not marker.exists(), f"marker still present after uninstall: {marker}"
        assert not is_installed(component_id, sb.repo)
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_uninstall_removes_required_managed_files(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"uninstall-rm-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        descriptor = all_descriptors()[component_id]
        required = [
            sb.repo / cf.rel_path
            for cf in descriptor.files
            if cf.lifecycle == MODE_REQUIRED_MANAGED and not cf.recursive
        ]

        uninstall_component(component_id, sb.repo)

        for path in required:
            assert not path.exists(), f"{component_id}: required-managed file not removed: {path}"
    finally:
        sb.cleanup()


@pytest.mark.parametrize("component_id", _component_ids())
def test_uninstall_preserves_create_if_missing_files(component_id: str, tmp_path: Path) -> None:
    """User-seeded config files must survive a default uninstall."""
    sb = sandbox_helper.create(tmp_path, f"uninstall-preserve-{component_id}")
    try:
        _install_with_deps(component_id, sb.repo)
        descriptor = all_descriptors()[component_id]
        config_paths = [
            sb.repo / cf.rel_path
            for cf in descriptor.files
            if cf.lifecycle == MODE_CREATE_IF_MISSING
            and cf.rel_path != descriptor.detection_marker
            and not cf.recursive
        ]
        # Only check files that were actually created during install
        existing_before = [p for p in config_paths if p.exists()]

        uninstall_component(component_id, sb.repo)

        for path in existing_before:
            assert path.exists(), f"{component_id}: config file incorrectly removed: {path}"
    finally:
        sb.cleanup()


# ---------------------------------------------------------------------------
# Full round-trip: install → disable → enable → uninstall
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("component_id", _component_ids())
def test_full_lifecycle_roundtrip(component_id: str, tmp_path: Path) -> None:
    sb = sandbox_helper.create(tmp_path, f"roundtrip-{component_id}")
    try:
        # Install
        _install_with_deps(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)

        # Disable — state only, files intact
        disable_component(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert not is_enabled(component_id, sb.repo)

        # Enable — restored
        enable_component(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)

        # Uninstall — marker gone, is_installed False
        uninstall_component(component_id, sb.repo)
        assert not is_installed(component_id, sb.repo)
    finally:
        sb.cleanup()
