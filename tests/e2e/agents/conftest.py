"""E2E fixtures for gateway docker tests."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _docker_project_root() -> str:
    """Return the project root path in a format Docker accepts for volume mounts.

    On Windows (Git Bash / MSYS2), pathlib gives a POSIX-style path like
    /h/development/... which Docker Desktop does not recognise. We convert it
    to a Windows mixed-format path (H:/development/...) that Docker Desktop
    accepts on all backends (WSL2 and Hyper-V).
    """
    import subprocess as _sp
    import sys
    root = Path(__file__).resolve().parents[2]
    if sys.platform.startswith("win"):
        return str(root)
    try:
        r = _sp.run(["cygpath", "-m", str(root)], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
    return str(root)


PROJECT_ROOT = _docker_project_root()
GATEWAY_CRASH_MATRIX_IMAGE = "audiagentic-gateway-crash-matrix:local"
GATEWAY_OPENCODE_IMAGE = "audiagentic-gateway-opencode:local"
GATEWAY_CONCURRENCY_IMAGE = "audiagentic-gateway-concurrency:local"
GATEWAY_PI_SMOKE_IMAGE = "audiagentic-gateway-pi-smoke:local"
DOCKER_EXE = shutil.which("docker")


def _docker_image_exists(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


requires_docker = pytest.mark.skipif(
    DOCKER_EXE is None,
    reason="docker not on PATH",
)

requires_gateway_crash_matrix_image = pytest.mark.skipif(
    not _docker_image_exists(GATEWAY_CRASH_MATRIX_IMAGE),
    reason=f"Docker image '{GATEWAY_CRASH_MATRIX_IMAGE}' not built — run: make build-gateway-crash-matrix",
)

requires_gateway_opencode_image = pytest.mark.skipif(
    not _docker_image_exists(GATEWAY_OPENCODE_IMAGE),
    reason=f"Docker image '{GATEWAY_OPENCODE_IMAGE}' not built — run: make build-gateway-opencode",
)

requires_gateway_concurrency_image = pytest.mark.skipif(
    not _docker_image_exists(GATEWAY_CONCURRENCY_IMAGE),
    reason=f"Docker image '{GATEWAY_CONCURRENCY_IMAGE}' not built — run: make build-gateway-concurrency",
)

requires_gateway_pi_smoke_image = pytest.mark.skipif(
    not _docker_image_exists(GATEWAY_PI_SMOKE_IMAGE),
    reason=f"Docker image '{GATEWAY_PI_SMOKE_IMAGE}' not built — run: make build-gateway-pi-smoke",
)
