"""E2E: consumer pipeline (AS19/AS30/AS31) Docker integration tests.

Runs the full AS19 status observer, AS30 session binding, and AS31 output
relay test suite inside the audiagentic-consumer-pipeline container.
Validates end-to-end consumer pipeline behavior with real process isolation.

Run via: make test-consumer-pipeline-docker
Skip conditions:
  - docker not on PATH
  - audiagentic-consumer-pipeline:local image not built
    (run: make build-consumer-pipeline)
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.agents.conftest import (
    CONSUMER_PIPELINE_IMAGE,
    DOCKER_EXE,
    requires_consumer_pipeline_image,
    requires_docker,
)


@requires_docker
@requires_consumer_pipeline_image
@pytest.mark.requires_docker
@pytest.mark.slow
@pytest.mark.timeout(300)
def test_consumer_pipeline_docker() -> None:
    """Run the full AS19/AS30/AS31 consumer pipeline integration suite in Docker.

    Tests:
      - AS19: observer ingress lifecycle (create, deliver, invalidate)
      - AS30: session binding durability and cross-process safety
      - AS31: output relay persistence, fragment bounds, monotonicity
      - Full pipeline: AS19+AS30+AS31 end-to-end together
    """
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", CONSUMER_PIPELINE_IMAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"consumer pipeline docker test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    # All tests should pass — check for expected output markers.
    assert "passed" in result.stdout.lower(), (
        f"No passing tests detected in output.\nstdout:\n{result.stdout}"
    )
    assert "failed" not in result.stdout.lower() or "0 failed" in result.stdout, (
        f"Test failures detected.\nstdout:\n{result.stdout}"
    )
