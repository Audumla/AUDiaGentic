"""E2E: Shell step stdout capture test inside Docker (Linux).

Validates that `echo` stdout is captured correctly on Unix shells.
Windows skips this test due to shell differences; Docker provides a
Linux environment where the test is valid.

Run via: make test-docker (the suite image) — or the docker phase of run_all.py
Skip conditions:
  - docker not on PATH
  - audiagentic-test image not built (run: make build-test)

This reuses the unified suite image rather than a dedicated one: that image
already bakes the tests and runs this exact case inside Linux as part of the
clean non-mutating suite. Here we invoke just the single test for a fast,
targeted Windows-dev check of Unix shell stdout capture.

Timeout: 60s — simple echo test.
"""
from __future__ import annotations

import subprocess

import pytest
from tests.e2e.coding_lsp.conftest import DOCKER_EXE, requires_docker

SUITE_IMAGE = "audiagentic-test:latest"
SHELL_TEST = (
    "tests/unit/foundation/workflow/test_steps.py::"
    "TestShellStep::test_stdout_captured_in_outputs"
)


def _image_exists() -> bool:
    if DOCKER_EXE is None:
        return False
    try:
        result = subprocess.run(
            [DOCKER_EXE, "image", "inspect", SUITE_IMAGE],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@requires_docker
@pytest.mark.skipif(not _image_exists(), reason=f"Docker image '{SUITE_IMAGE}' not built — run: make build-test")
@pytest.mark.docker
@pytest.mark.timeout(60)
def test_shell_stdout_captured_in_docker() -> None:
    """Shell step stdout capture test runs inside Linux Docker container."""
    result = subprocess.run(
        [DOCKER_EXE, "run", "--rm", SUITE_IMAGE, "pytest", SHELL_TEST, "-q"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Shell stdout test failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    # With -q in addopts the summary "N passed" is suppressed; check completion marker.
    assert "[100%]" in result.stdout, (
        f"Expected [100%] in pytest output.\n--- stdout ---\n{result.stdout}"
    )
