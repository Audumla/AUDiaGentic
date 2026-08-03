"""E2E: SH07 gateway crash-recovery matrix inside Docker.

Runs the real-subprocess crash-matrix suite (agents_gateway_service_process
killed at specific control-plane phases, restarted, recovery verified)
inside the audiagentic-gateway-crash-matrix container.

Run via: make test-gateway-crash-matrix-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-gateway-crash-matrix:local image not built
    (run: make build-gateway-crash-matrix)
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.agents.conftest import (
    DOCKER_EXE,
    GATEWAY_CRASH_MATRIX_IMAGE,
    requires_container,
    requires_gateway_crash_matrix_image,
)


@requires_container
@requires_gateway_crash_matrix_image
@pytest.mark.requires_container
@pytest.mark.slow
@pytest.mark.timeout(300)
def test_gateway_crash_matrix_recovers_correctly() -> None:
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", GATEWAY_CRASH_MATRIX_IMAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"gateway crash-matrix docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "passed" in result.stdout and "failed" not in result.stdout
