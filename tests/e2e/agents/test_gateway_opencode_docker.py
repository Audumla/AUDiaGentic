"""E2E: real opencode CLI + real gateway inside Docker.

Runs the real-opencode-install suite (npm CLI install, harness runtime
install, real gateway dispatch, cancel/rejection negative paths) inside the
audiagentic-gateway-opencode container.

Run via: make test-gateway-opencode-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-gateway-opencode:local image not built
    (run: make build-gateway-opencode)
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.agents.conftest import (
    DOCKER_EXE,
    GATEWAY_OPENCODE_IMAGE,
    requires_docker,
    requires_gateway_opencode_image,
)


@requires_docker
@requires_gateway_opencode_image
@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.mutates_host
@pytest.mark.timeout(300)
def test_gateway_opencode_real_cli_and_negative_paths() -> None:
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", GATEWAY_OPENCODE_IMAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"gateway opencode docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "passed" in result.stdout and "failed" not in result.stdout
