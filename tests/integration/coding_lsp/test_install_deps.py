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

from audiagentic.components.optional.coding_lsp.lsp_dependencies import get_lsp_dependencies
from audiagentic.foundation.dependencies import (
    SYSTEM_DEPENDENCIES,
    detect_missing,
    install_dependencies,
    uninstall_dependencies,
)
from audiagentic.foundation.invoke.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    privilege_prefix,
)

pytestmark = [pytest.mark.mutates_host, pytest.mark.slow]

ALL_SERVERS = ["pyright", "typescript-language-server", "rust-analyzer", "clangd"]
FAST_SERVERS = ["pyright", "typescript-language-server", "clangd"]

BINARY: dict[str, str] = {
    "pyright": "pyright-langserver",
    "typescript-language-server": "typescript-language-server",
    "rust-analyzer": "rust-analyzer",
    "clangd": "clangd",
}


def _ok_count(results: dict) -> int:
    return sum(1 for r in results["results"] if r.get("ok"))


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
    missing = detect_missing(SYSTEM_DEPENDENCIES, [tool])
    assert tool not in missing, f"{tool} should be pre-installed in base image"


# ---------------------------------------------------------------------------
# PlatformRecipe resolution
# ---------------------------------------------------------------------------

def test_clangd_platform_recipe_resolves() -> None:
    from audiagentic.foundation.invoke.context import InvocationContext
    deps = get_lsp_dependencies()
    ctx = InvocationContext()
    plan = deps["clangd"].install.plan(ctx)
    assert plan.status != "failed", f"clangd PlatformRecipe resolution failed: {plan}"


# ---------------------------------------------------------------------------
# Install all 4 LSP servers
# ---------------------------------------------------------------------------

@pytest.mark.timeout(900)
def test_install_all_lsp_servers() -> None:
    deps = get_lsp_dependencies()
    missing_before = detect_missing(deps, ALL_SERVERS)
    if not missing_before:
        pytest.skip("all LSP servers already present — skipping install")

    result = install_dependencies(deps, missing_before)
    assert _ok_count(result) == len(missing_before), (
        f"not all servers installed: {[r for r in result['results'] if not r.get('ok')]}"
    )


@pytest.mark.timeout(900)
@pytest.mark.parametrize("server", ALL_SERVERS)
def test_lsp_binary_present_after_install(server: str) -> None:
    binary = BINARY[server]
    assert shutil.which(binary) is not None, f"{server} ({binary}) not on PATH after install"


@pytest.mark.timeout(900)
def test_detect_missing_empty_after_install() -> None:
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, ALL_SERVERS)
    assert missing == [], f"servers still missing after install: {missing}"


# ---------------------------------------------------------------------------
# Uninstall fast servers (rust-analyzer excluded — see module docstring)
# ---------------------------------------------------------------------------

@pytest.mark.timeout(300)
def test_uninstall_fast_lsp_servers() -> None:
    deps = get_lsp_dependencies()
    result = uninstall_dependencies(deps, FAST_SERVERS)
    assert _ok_count(result) == len(FAST_SERVERS), (
        f"not all fast servers uninstalled: {[r for r in result['results'] if not r.get('ok')]}"
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
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, ALL_SERVERS)
    assert server in missing, f"{server} should be reported missing after uninstall"


@pytest.mark.timeout(300)
def test_detect_missing_does_not_report_rust_analyzer() -> None:
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, ALL_SERVERS)
    assert "rust-analyzer" not in missing, "rust-analyzer should not be reported missing"


# ---------------------------------------------------------------------------
# Install/uninstall cycle — pyright
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
def test_pyright_reinstall_cycle() -> None:
    deps = get_lsp_dependencies()

    reinstall = install_dependencies(deps, ["pyright"])
    assert _ok_count(reinstall) == 1, f"pyright reinstall failed: {reinstall}"
    assert shutil.which(BINARY["pyright"]) is not None, "pyright binary absent after reinstall"

    re_uninstall = uninstall_dependencies(deps, ["pyright"])
    assert _ok_count(re_uninstall) == 1, f"pyright second uninstall failed: {re_uninstall}"
    assert shutil.which(BINARY["pyright"]) is None, "pyright binary present after second uninstall"

    missing_end = detect_missing(deps, ["pyright"])
    assert "pyright" in missing_end, "pyright should be reported missing after cycle end"
