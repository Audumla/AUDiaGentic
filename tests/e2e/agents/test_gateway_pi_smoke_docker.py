"""E2E: SH16 real Pi CLI + embedded rig gateway dispatch inside Docker.

Runs the real Pi CLI-install + real embedded llama-server rig + real gateway
full-isolation dispatch suite (test_gateway_pi_smoke.py) inside the
audiagentic-gateway-pi-smoke container.

Run via: make test-gateway-pi-smoke-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-gateway-pi-smoke:local image not built
    (run: make build-gateway-pi-smoke)
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.agents.conftest import (
    DOCKER_EXE,
    GATEWAY_PI_SMOKE_IMAGE,
    requires_docker,
    requires_gateway_pi_smoke_image,
)


@requires_docker
@requires_gateway_pi_smoke_image
@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_gateway_pi_smoke_real_dispatch() -> None:
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", GATEWAY_PI_SMOKE_IMAGE],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, (
        f"gateway pi smoke docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "passed" in result.stdout and "failed" not in result.stdout
