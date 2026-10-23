"""CI images must not depend on ignored developer-local generated surfaces."""
import shlex
from fnmatch import fnmatchcase
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("workflow", ["ci-tests", "ci-contracts"])
def test_ci_triggers_do_not_duplicate_feature_branch_pr_runs(workflow):
    # YAML 1.1 SafeLoader interprets the Actions key `on` as boolean True.
    config = yaml.load((ROOT / ".github/workflows" / f"{workflow}.yml").read_text(), Loader=yaml.BaseLoader)
    triggers = config["on"]
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert not triggers["pull_request"]  # retain default events for every PR/base/fork
    patterns = triggers["push"]["branches"]
    assert patterns == ["main", "proof-release-*"]
    for branch, expected in [("main", True), ("proof-release-ci", True), ("fix/worker-progress", False), ("feature/example", False)]:
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
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
