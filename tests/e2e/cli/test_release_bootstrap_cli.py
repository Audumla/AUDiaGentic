"""E2E: `audiagentic release-bootstrap` CLI command."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import subprocess


def _cli(*args: str, project: Path | None = None, expect_rc: int = 0) -> dict | list | None:
    cmd = [sys.executable, "-m", "audiagentic.launcher"]
    if project is not None:
        cmd += ["--project", str(project)]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == expect_rc, (
        f"CLI {args!r} rc={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    stdout = result.stdout.strip()
    return json.loads(stdout) if stdout else None


def test_release_bootstrap_returns_ok(tmp_path):
    result = _cli("release-bootstrap", project=tmp_path)
    assert result is not None
    assert result.get("ok") is True or result.get("status") == "success"


def test_release_bootstrap_writes_core_lifecycle_marker(tmp_path):
    _cli("release-bootstrap", project=tmp_path)
    marker = tmp_path / ".audiagentic" / "components" / "core-lifecycle.yaml"
    assert marker.is_file()


def test_release_bootstrap_marker_has_expected_fields(tmp_path):
    _cli("release-bootstrap", project=tmp_path)
    import yaml
    marker = tmp_path / ".audiagentic" / "components" / "core-lifecycle.yaml"
    data = yaml.safe_load(marker.read_text(encoding="utf-8"))
    assert data["component-id"] == "core-lifecycle"
    assert data["enabled"] is True
    assert "installed-at" in data
    assert "version" in data


def test_release_bootstrap_syncs_managed_files(tmp_path):
    _cli("release-bootstrap", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    assert project_yaml.is_file()


def test_release_bootstrap_custom_release_id(tmp_path):
    result = _cli("release-bootstrap", "--release-id", "rel_custom_01", project=tmp_path)
    assert result is not None


def test_release_bootstrap_second_call_is_update(tmp_path):
    _cli("release-bootstrap", project=tmp_path)
    import yaml
    marker = tmp_path / ".audiagentic" / "components" / "core-lifecycle.yaml"
    first_installed_at = yaml.safe_load(marker.read_text(encoding="utf-8"))["installed-at"]

    _cli("release-bootstrap", project=tmp_path)
    data = yaml.safe_load(marker.read_text(encoding="utf-8"))
    assert data["installation-kind"] == "update"
    assert data["installed-at"] == first_installed_at
