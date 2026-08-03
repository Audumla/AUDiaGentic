"""E2E: real concurrent gateway load inside Docker.

Runs the real-subprocess concurrency suite (max-concurrency saturation,
cross-project lane sharing, queue-max-size rejection, reload-vs-load races,
cancel-vs-concurrent-dispatch) inside the audiagentic-gateway-concurrency
container.

Run via: make test-gateway-concurrency-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-gateway-concurrency:local image not built
    (run: make build-gateway-concurrency)
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.agents.conftest import (
    DOCKER_EXE,
    GATEWAY_CONCURRENCY_IMAGE,
    requires_docker,
    requires_gateway_concurrency_image,
)


@requires_docker
@requires_gateway_concurrency_image
@pytest.mark.requires_docker
@pytest.mark.slow
@pytest.mark.timeout(300)
def test_gateway_concurrency_real_load() -> None:
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", GATEWAY_CONCURRENCY_IMAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"gateway concurrency docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "passed" in result.stdout and "failed" not in result.stdout
