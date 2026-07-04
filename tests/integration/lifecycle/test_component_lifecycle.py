"""Integration tests: component lifecycle — install, disable, enable, uninstall."""
from __future__ import annotations

from pathlib import Path

import pytest
from tests.integration.lifecycle.harness import (
    all_descriptors,
    component_sandbox,
    create_if_missing_paths,
    disable_component,
    enable_component,
    install_component,
    install_with_deps,
    is_enabled,
    is_installed,
    marker_data,
    marker_path,
    project_component_ids,
    required_managed_paths,
    uninstall_component,
    user_config_paths,
)


@pytest.mark.parametrize("component_id", project_component_ids())
def test_install_writes_marker(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"install-marker-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)

        marker = marker_path(component_id, sb.repo)
        assert marker.is_file(), f"marker missing after install: {marker}"

        data = marker_data(component_id, sb.repo)
        assert data.get("component-id") == component_id
        assert data.get("enabled") is True
        assert "installed-at" in data


@pytest.mark.parametrize("component_id", project_component_ids())
def test_install_sets_is_installed(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"install-state-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)


@pytest.mark.parametrize("component_id", project_component_ids())
def test_install_creates_required_managed_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"install-files-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        for target in required_managed_paths(component_id, sb.repo):
            assert target.is_file(), f"{component_id}: required-managed file missing: {target}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_install_creates_create_if_missing_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"install-cim-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        for target in create_if_missing_paths(component_id, sb.repo):
            assert target.is_file(), f"{component_id}: create-if-missing file missing after install: {target}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_disable_sets_enabled_false(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"disable-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        result = disable_component(component_id, sb.repo)
        assert result.get("ok") is True
        assert not is_enabled(component_id, sb.repo)
        assert marker_data(component_id, sb.repo).get("enabled") is False


@pytest.mark.parametrize("component_id", project_component_ids())
def test_disable_does_not_remove_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"disable-files-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        disable_component(component_id, sb.repo)
        for target in required_managed_paths(component_id, sb.repo):
            assert target.is_file(), f"{component_id}: file disappeared after disable: {target}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_enable_after_disable(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"enable-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        disable_component(component_id, sb.repo)
        assert not is_enabled(component_id, sb.repo)

        result = enable_component(component_id, sb.repo)
        assert result.get("ok") is True
        assert is_enabled(component_id, sb.repo)
        assert marker_data(component_id, sb.repo).get("enabled") is True


@pytest.mark.parametrize("component_id", project_component_ids())
def test_uninstall_removes_marker(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"uninstall-marker-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        marker = marker_path(component_id, sb.repo)
        assert marker.is_file()

        uninstall_component(component_id, sb.repo)

        assert not marker.exists(), f"marker still present after uninstall: {marker}"
        assert not is_installed(component_id, sb.repo)


@pytest.mark.parametrize("component_id", project_component_ids())
def test_uninstall_removes_required_managed_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"uninstall-rm-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        required = required_managed_paths(component_id, sb.repo)

        uninstall_component(component_id, sb.repo)

        for path in required:
            assert not path.exists(), f"{component_id}: required-managed file not removed: {path}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_uninstall_preserves_create_if_missing_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"uninstall-preserve-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        existing_before = [path for path in user_config_paths(component_id, sb.repo) if path.exists()]

        uninstall_component(component_id, sb.repo)

        for path in existing_before:
            assert path.exists(), f"{component_id}: config file incorrectly removed: {path}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_uninstall_remove_configs_removes_create_if_missing_files(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"uninstall-force-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        existing_before = [path for path in create_if_missing_paths(component_id, sb.repo) if path.exists()]

        uninstall_component(component_id, sb.repo, remove_configs=True)

        marker = marker_path(component_id, sb.repo)
        assert not marker.exists(), f"{component_id}: marker still present after forced uninstall"
        assert not is_installed(component_id, sb.repo)
        for path in existing_before:
            assert not path.exists(), f"{component_id}: create-if-missing file not removed with remove_configs=True: {path}"


@pytest.mark.parametrize("component_id", project_component_ids())
def test_full_lifecycle_roundtrip(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"roundtrip-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)

        disable_component(component_id, sb.repo)
        assert is_installed(component_id, sb.repo)
        assert not is_enabled(component_id, sb.repo)

        enable_component(component_id, sb.repo)
        assert is_enabled(component_id, sb.repo)

        uninstall_component(component_id, sb.repo)
        assert not is_installed(component_id, sb.repo)


def test_install_surfaces_missing_dependencies_as_next_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.coding_lsp import coding_lsp_bootstrap

    with component_sandbox(tmp_path, "install-missing-deps-coding-lsp") as sb:
        install_with_deps("coding-lsp", sb.repo)

        monkeypatch.setattr(coding_lsp_bootstrap, "_active_dependency_ids", lambda project_root: ["clangd"])
        monkeypatch.setattr(coding_lsp_bootstrap, "detect_missing", lambda probes, ids: ["clangd"])
        result = install_component("coding-lsp", sb.repo)

        details = result["component_status"]["details"]
        assert details.get("missing_dependencies") == ["clangd"]
        assert "next-step" in result
        assert "clangd" in result["next-step"]


def test_project_component_selector_matches_registry_contract() -> None:
    selected = set(project_component_ids())
    expected = {
        component_id
        for component_id, descriptor in all_descriptors().items()
        if descriptor.scope == "project" and not descriptor.core
    }
    assert selected == expected


# --- sync payload ---

@pytest.mark.parametrize("component_id", project_component_ids())
def test_install_sync_target_is_project(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"sync-install-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        result = install_component(component_id, sb.repo)
        sync = result.get("sync", {})
        assert sync.get("target") == "project", (
            f"{component_id}: sync.target should be 'project', got {sync.get('target')!r}"
        )


@pytest.mark.parametrize("component_id", project_component_ids())
def test_disable_sync_action_reflects_mcp_servers(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"sync-disable-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        result = disable_component(component_id, sb.repo)
        sync = result.get("sync", {})
        descriptor = all_descriptors()[component_id]
        has_mcp = bool(descriptor.mcp_servers or descriptor.external_mcp_servers)
        expected_action = "reload_required" if has_mcp else "refresh_required"
        assert sync.get("action") == expected_action, (
            f"{component_id}: sync.action={sync.get('action')!r}, expected={expected_action!r} "
            f"(has_mcp={has_mcp})"
        )


@pytest.mark.parametrize("component_id", project_component_ids())
def test_enable_sync_action_reflects_mcp_servers(component_id: str, tmp_path: Path) -> None:
    with component_sandbox(tmp_path, f"sync-enable-{component_id}") as sb:
        install_with_deps(component_id, sb.repo)
        disable_component(component_id, sb.repo)
        result = enable_component(component_id, sb.repo)
        sync = result.get("sync", {})
        descriptor = all_descriptors()[component_id]
        has_mcp = bool(descriptor.mcp_servers or descriptor.external_mcp_servers)
        expected_action = "reload_required" if has_mcp else "refresh_required"
        assert sync.get("action") == expected_action, (
            f"{component_id}: sync.action={sync.get('action')!r}, expected={expected_action!r} "
            f"(has_mcp={has_mcp})"
        )
