"""CI images must not depend on ignored developer-local generated surfaces."""

import shlex
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("workflow", ["ci-tests", "ci-full"])
def test_cdp_recovery_gates_install_optional_socket_dependency(workflow):
    text = (ROOT / ".github/workflows" / f"{workflow}.yml").read_text()
    assert '.[test,acp,a2a,gpt-auto,node]' in text


def test_the_a2a_extra_is_installed_so_the_sdk_tests_run_instead_of_skipping():
    """tests/unit/agents/test_a2a_sdk_handler.py importorskips the SDK; CI must have it or the wire tests never run."""
    import tomllib

    extras = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    assert any(requirement.startswith("a2a-sdk[http-server]==") for requirement in extras["a2a"])
    constraints = (ROOT / "tests/ci/requirements.txt").read_text()
    assert "\na2a-sdk==" in constraints and "\nstarlette==" in constraints and "\nsse-starlette==" in constraints
    for workflow in ("ci-tests", "ci-full"):
        assert ",a2a," in (ROOT / ".github/workflows" / f"{workflow}.yml").read_text()


@pytest.mark.parametrize("workflow", ["ci-tests", "ci-contracts"])
def test_ci_triggers_do_not_duplicate_feature_branch_pr_runs(workflow):
    # YAML 1.1 SafeLoader interprets the Actions key `on` as boolean True.
    config = yaml.load(
        (ROOT / ".github/workflows" / f"{workflow}.yml").read_text(), Loader=yaml.BaseLoader
    )
    triggers = config["on"]
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"} | (
        {"workflow_call"} if workflow == "ci-tests" else set()
    )
    assert not triggers["pull_request"]  # retain default events for every PR/base/fork
    patterns = triggers["push"]["branches"]
    assert patterns == ["main", "proof-release-*"]
    for branch, expected in [
        ("main", True),
        ("proof-release-ci", True),
        ("fix/worker-progress", False),
        ("feature/example", False),
    ]:
        assert any(fnmatchcase(branch, pattern) for pattern in patterns) is expected


@pytest.mark.parametrize("image", ["test", "packaging", "acp-e2e", "gateway-concurrency"])
def test_ci_docker_copy_sources_exist_in_checkout(image):
    for line in (ROOT / "tests/docker" / f"Dockerfile.{image}").read_text().splitlines():
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        for source in shlex.split(line)[1:-1]:
            assert (ROOT / source).exists(), f"{image}: absent COPY input {source}"


def test_non_browser_gateway_imports_without_websockets():
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'websockets' or name.startswith('websockets.'):
        raise ModuleNotFoundError('browser dependency intentionally absent')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import audiagentic.components.agents.gateway.service.process
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
