"""E2E: LSP dependency install/uninstall/cycle inside Docker.

Runs the comprehensive install-deps script inside the audiagentic-lsp-install-test
container. Covers:
  - Install all 4 LSP servers (pyright, typescript-language-server, rust-analyzer, clangd)
  - Verify binaries on PATH and detect_missing accuracy
  - Uninstall fast servers (pyright, typescript-language-server, clangd)
  - Verify binaries gone and detect_missing reports correctly
  - Full install/uninstall cycle for pyright
  - Privilege detection, platform detection, and PlatformRecipe resolution
  - System dependency state check (git, gh, uv pre-installed in base image)

Run via: make test-lsp-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-lsp-install-test image not built (run: make build-lsp-install)

Timeout: 1800s (30 min) — rust-analyzer compiles from source (~10-15 min).
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.coding_lsp.conftest import (
    DOCKER_EXE,
    LSP_IMAGE,
    PROJECT_ROOT,
    requires_docker,
    requires_lsp_image,
)


@requires_docker
@requires_lsp_image
@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_lsp_full_install_uninstall_cycle() -> None:
    """Full LSP lifecycle: install all 4 servers, uninstall fast servers, reinstall pyright."""
    result = subprocess.run(
        [
            DOCKER_EXE, "run", "--rm",
            "-v", f"{PROJECT_ROOT}:/app",
            LSP_IMAGE,
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    # Surface full output on failure for diagnosability
    assert result.returncode == 0, (
        f"LSP docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "passed" in result.stdout and "failed" not in result.stdout


@requires_docker
@requires_lsp_image
@pytest.mark.docker
@pytest.mark.timeout(30)
def test_lsp_install_image_has_required_toolchains() -> None:
    """The LSP test image has all required toolchains (npm, uv, cargo, apt-get)."""
    for tool in ("npm", "uv", "cargo", "apt-get"):
        result = subprocess.run(
            [DOCKER_EXE, "run", "--rm", LSP_IMAGE, "bash", "-c", f"which {tool}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Tool '{tool}' missing from {LSP_IMAGE}"
