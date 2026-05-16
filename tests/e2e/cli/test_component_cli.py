"""E2E tests for `audiagentic component` CLI subcommands.

These run inside Docker (AUDIAGENTIC_DOCKER_TESTS=1) so they can freely write to tmp_path.
Each test calls the CLI via subprocess so it exercises the installed entry point exactly as
a release user would.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import subprocess

import pytest


def _cli(*args: str, project: Path | None = None, expect_rc: int = 0) -> dict | list | None:
    cmd = [sys.executable, "-m", "audiagentic.launcher"]
    if project is not None:
        cmd += ["--project", str(project)]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == expect_rc, (
        f"CLI {args!r} returned rc={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    stdout = result.stdout.strip()
    return json.loads(stdout) if stdout else None


# ── list ──────────────────────────────────────────────────────────────────────

def test_component_list_returns_all_registered(tmp_path):
    rows = _cli("component", "list", project=tmp_path)
    assert isinstance(rows, list)
    ids = {r["component_id"] for r in rows}
    assert "core-lifecycle" in ids
    assert len(ids) >= 7


def test_component_list_shows_not_installed_for_fresh_dir(tmp_path):
    rows = _cli("component", "list", project=tmp_path)
    for row in rows:
        assert row["installed"] is False
        assert row["enabled"] is None


# ── status ────────────────────────────────────────────────────────────────────

def test_status_not_installed(tmp_path):
    result = _cli("component", "status", "core-lifecycle", project=tmp_path)
    assert result["installed"] is False
    assert result["enabled"] is None


def test_status_unknown_component(tmp_path):
    _cli("component", "status", "no-such-component", project=tmp_path, expect_rc=1)


# ── install → status → disable → enable → uninstall ──────────────────────────

LIFECYCLE_COMPONENTS = [
    "core-lifecycle",
    "provider-layer",
    "planning",
    "release-audit-ledger",
    "agent-jobs",
]


@pytest.mark.parametrize("component_id", LIFECYCLE_COMPONENTS)
def test_install_sets_installed_and_enabled(tmp_path, component_id):
    result = _cli("component", "install", component_id, project=tmp_path)
    assert result["ok"] is True
    assert result["component_id"] == component_id

    status = _cli("component", "status", component_id, project=tmp_path)
    assert status["installed"] is True
    assert status["enabled"] is True


@pytest.mark.parametrize("component_id", LIFECYCLE_COMPONENTS)
def test_disable_sets_enabled_false(tmp_path, component_id):
    _cli("component", "install", component_id, project=tmp_path)

    result = _cli("component", "disable", component_id, project=tmp_path)
    assert result["ok"] is True
    assert result["enabled"] is False

    status = _cli("component", "status", component_id, project=tmp_path)
    assert status["installed"] is True
    assert status["enabled"] is False


@pytest.mark.parametrize("component_id", LIFECYCLE_COMPONENTS)
def test_enable_after_disable(tmp_path, component_id):
    _cli("component", "install", component_id, project=tmp_path)
    _cli("component", "disable", component_id, project=tmp_path)

    result = _cli("component", "enable", component_id, project=tmp_path)
    assert result["ok"] is True
    assert result["enabled"] is True

    status = _cli("component", "status", component_id, project=tmp_path)
    assert status["enabled"] is True


@pytest.mark.parametrize("component_id", LIFECYCLE_COMPONENTS)
def test_uninstall_removes_marker(tmp_path, component_id):
    _cli("component", "install", component_id, project=tmp_path)

    marker = tmp_path / ".audiagentic" / "components" / f"{component_id}.yaml"
    assert marker.exists()

    result = _cli("component", "uninstall", component_id, project=tmp_path)
    assert result["ok"] is True

    assert not marker.exists()

    status = _cli("component", "status", component_id, project=tmp_path)
    assert status["installed"] is False


@pytest.mark.parametrize("component_id", LIFECYCLE_COMPONENTS)
def test_full_lifecycle_roundtrip(tmp_path, component_id):
    """install → disable → enable → uninstall — state correct at each step."""
    status = _cli("component", "status", component_id, project=tmp_path)
    assert status["installed"] is False

    _cli("component", "install", component_id, project=tmp_path)
    assert _cli("component", "status", component_id, project=tmp_path)["installed"] is True

    _cli("component", "disable", component_id, project=tmp_path)
    assert _cli("component", "status", component_id, project=tmp_path)["enabled"] is False

    _cli("component", "enable", component_id, project=tmp_path)
    assert _cli("component", "status", component_id, project=tmp_path)["enabled"] is True

    _cli("component", "uninstall", component_id, project=tmp_path)
    assert _cli("component", "status", component_id, project=tmp_path)["installed"] is False
