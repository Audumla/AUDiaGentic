"""Docker installation integration tests for coding_lsp dependencies.

Run inside the Docker container built from tests/docker/Dockerfile.lsp-install-test.
Validates install, uninstall, and reinstall operations for all four LSP servers,
plus privilege/platform detection and system dependency state checks.

rust-analyzer is excluded from the uninstall/cycle tests — compiling from source
takes >10 min; cycling adds no value and doubles the already-long build time.
"""
from __future__ import annotations

import shutil

import pytest

from audiagentic.components.coding_lsp import language_registry
from audiagentic.foundation.components.dependencies import (
    build_dependency_probes,
    build_dependency_workflow,
    detect_missing,
    load_dependency_probes,
)
from audiagentic.foundation.steps import SelectStep, SequenceStep
from audiagentic.foundation.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    privilege_prefix,
)

pytestmark = [pytest.mark.mutates_host, pytest.mark.slow]


def load_dependency_workflow_lsp(action: str = "install"):
    """Build the coding-lsp dependency workflow from the per-language registry."""
    return build_dependency_workflow(
        language_registry.dependency_cfgs(), workflow_id="coding-lsp", action=action
    )

ALL_SERVERS = ["pyright", "typescript-language-server", "rust-analyzer", "clangd"]
FAST_SERVERS = ["pyright", "typescript-language-server", "clangd"]

BINARY: dict[str, str] = {
    "pyright": "pyright-langserver",
    "typescript-language-server": "typescript-language-server",
    "rust-analyzer": "rust-analyzer",
    "clangd": "clangd",
}

_SYSTEM_PROBES = load_dependency_probes("source-control")
_LSP_PROBES = build_dependency_probes(language_registry.dependency_cfgs())


def _run_subset(workflow: SequenceStep, names: list[str]) -> dict:
    steps = tuple(s for s in workflow.steps if s.id in names)
    seq = SequenceStep(id="subset", steps=steps, fail_fast=False)
    result = seq.run({})
    ok_count = sum(
        1 for v in result.outputs.values()
        if isinstance(v, dict) and v.get("status") in ("ok", "skipped")
        or not isinstance(v, dict)
    )
    return {"result": result, "ok_count": len(steps)}


def _ok_count(result) -> int:
    return sum(
        1 for v in result.outputs.values()
        if not isinstance(v, dict) or v.get("status") in ("ok", "skipped")
    )


# ---------------------------------------------------------------------------
# Toolchain availability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["uv", "npm", "cargo", "apt-get", "git", "gh"])
def test_toolchain_available(tool: str) -> None:
    assert shutil.which(tool) is not None, f"{tool} not found on PATH"


# ---------------------------------------------------------------------------
# Privilege and platform detection
# ---------------------------------------------------------------------------

def test_running_as_root() -> None:
    assert privilege_prefix() == (), "expected no sudo prefix (running as root)"


def test_apt_selected_as_package_manager() -> None:
    pkg_mgr = detect_pkg_manager()
    assert pkg_mgr == "apt", f"expected apt, got {pkg_mgr}"


def test_platform_key_is_linux() -> None:
    assert platform_key() == "linux"


# ---------------------------------------------------------------------------
# System dependency state (pre-installed in base image)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["git", "gh", "uv"])
def test_system_dependency_present_in_base_image(tool: str) -> None:
    missing = detect_missing(_SYSTEM_PROBES, [tool])
    assert tool not in missing, f"{tool} should be pre-installed in base image"


# ---------------------------------------------------------------------------
# SelectStep resolution for platform-dispatched deps
# ---------------------------------------------------------------------------

def test_clangd_step_is_select_with_variants() -> None:
    workflow = load_dependency_workflow_lsp()
    clangd_step = next(s for s in workflow.steps if s.id == "clangd")
    assert isinstance(clangd_step, SelectStep)
    # inner install SelectStep should have apt variant
    inner = clangd_step.variants.get("run")
    assert inner is not None
    assert isinstance(inner, SelectStep)
    assert "apt" in inner.variants


# ---------------------------------------------------------------------------
# Install all 4 LSP servers
# ---------------------------------------------------------------------------

@pytest.mark.timeout(900)
def test_install_all_lsp_servers() -> None:
    missing_before = detect_missing(_LSP_PROBES, ALL_SERVERS)
    if not missing_before:
        pytest.skip("all LSP servers already present — skipping install")

    workflow = load_dependency_workflow_lsp(action="install")
    result = _run_subset(workflow, missing_before)
    assert result["ok_count"] == len(missing_before), (
        f"not all servers installed: {result['result'].outputs}"
    )


@pytest.mark.timeout(900)
@pytest.mark.parametrize("server", ALL_SERVERS)
def test_lsp_binary_present_after_install(server: str) -> None:
    binary = BINARY[server]
    assert shutil.which(binary) is not None, f"{server} ({binary}) not on PATH after install"


@pytest.mark.timeout(900)
def test_detect_missing_empty_after_install() -> None:
    missing = detect_missing(_LSP_PROBES, ALL_SERVERS)
    assert missing == [], f"servers still missing after install: {missing}"


# ---------------------------------------------------------------------------
# Uninstall fast servers (rust-analyzer excluded — see module docstring)
# ---------------------------------------------------------------------------

@pytest.mark.timeout(300)
def test_uninstall_fast_lsp_servers() -> None:
    workflow = load_dependency_workflow_lsp(action="uninstall")
    result = _run_subset(workflow, FAST_SERVERS)
    assert result["ok_count"] == len(FAST_SERVERS), (
        f"not all fast servers uninstalled: {result['result'].outputs}"
    )


@pytest.mark.timeout(300)
@pytest.mark.parametrize("server", FAST_SERVERS)
def test_fast_lsp_binary_absent_after_uninstall(server: str) -> None:
    binary = BINARY[server]
    assert shutil.which(binary) is None, f"{server} ({binary}) still on PATH after uninstall"


@pytest.mark.timeout(300)
def test_rust_analyzer_unaffected_by_fast_uninstall() -> None:
    assert shutil.which(BINARY["rust-analyzer"]) is not None, (
        "rust-analyzer should remain after fast-server uninstall"
    )


@pytest.mark.timeout(300)
@pytest.mark.parametrize("server", FAST_SERVERS)
def test_detect_missing_reports_uninstalled_fast_servers(server: str) -> None:
    missing = detect_missing(_LSP_PROBES, ALL_SERVERS)
    assert server in missing, f"{server} should be reported missing after uninstall"


@pytest.mark.timeout(300)
def test_detect_missing_does_not_report_rust_analyzer() -> None:
    missing = detect_missing(_LSP_PROBES, ALL_SERVERS)
    assert "rust-analyzer" not in missing, "rust-analyzer should not be reported missing"


# ---------------------------------------------------------------------------
# Install/uninstall cycle — pyright
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
def test_pyright_reinstall_cycle() -> None:
    install_wf = load_dependency_workflow_lsp(action="install")
    uninstall_wf = load_dependency_workflow_lsp(action="uninstall")

    reinstall = _run_subset(install_wf, ["pyright"])
    assert reinstall["ok_count"] == 1, f"pyright reinstall failed: {reinstall['result'].outputs}"
    assert shutil.which(BINARY["pyright"]) is not None, "pyright binary absent after reinstall"

    re_uninstall = _run_subset(uninstall_wf, ["pyright"])
    assert re_uninstall["ok_count"] == 1, f"pyright uninstall failed: {re_uninstall['result'].outputs}"
    assert shutil.which(BINARY["pyright"]) is None, "pyright binary present after second uninstall"

    assert "pyright" in detect_missing(_LSP_PROBES, ["pyright"])
