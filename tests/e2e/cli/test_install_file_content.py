"""E2E: verify that `component install` actually places correct file content on disk.

Tests that baseline_sync lands the right files from the template root — not just that
markers are written, but that the managed files are present and non-empty.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


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
    if not stdout:
        return None
    start = stdout.find("{")
    if start >= 0:
        return json.loads(stdout[start:])
    return json.loads(stdout)


# ── project file content ───────────────────────────────────────────────

def test_install_project_creates_prompt_files(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    prompt = tmp_path / ".audiagentic" / "prompts" / "ag-review" / "default.md"
    assert prompt.is_file(), f"expected prompt file at {prompt}"
    assert prompt.stat().st_size > 0


def test_install_release_creates_release_workflow(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    _cli("component", "install", "agent-ledger", project=tmp_path)
    _cli("component", "install", "release", project=tmp_path)
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    assert wf.is_file(), f"expected workflow at {wf}"
    content = wf.read_text(encoding="utf-8")
    assert "on:" in content or "jobs:" in content
    assert "PYTHONPATH: src" in content
    assert "from audiagentic.components.optional.release import release_api" in content
    assert "scripts/components/optional/ledger/finalize_ledger.py" not in content


def test_install_project_seeds_project_yaml(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    assert project_yaml.is_file()
    assert project_yaml.stat().st_size > 0


def test_reinstall_project_refreshes_required_managed(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    prompt = tmp_path / ".audiagentic" / "prompts" / "ag-review" / "default.md"
    original = prompt.read_text(encoding="utf-8")
    prompt.write_text("corrupted", encoding="utf-8")

    _cli("component", "install", "project", project=tmp_path)
    assert prompt.read_text(encoding="utf-8") == original


def test_reinstall_project_preserves_create_if_missing(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    project_yaml.write_text("contract-version: v1\nproject-id: my-project\n", encoding="utf-8")

    _cli("component", "install", "project", project=tmp_path)
    assert "my-project" in project_yaml.read_text(encoding="utf-8")



def test_install_agent_jobs_creates_skill_files(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    _cli("component", "install", "agent-jobs", project=tmp_path)
    skill = tmp_path / ".audiagentic" / "skills" / "ag-review" / "skill.md"
    assert skill.is_file(), f"expected skill file at {skill}"
    assert skill.stat().st_size > 0


# ── uninstall removes required-managed files for optional components ──────────

def test_uninstall_removes_release_required_managed_files(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    _cli("component", "install", "agent-ledger", project=tmp_path)
    _cli("component", "install", "release", project=tmp_path)
    workflow = tmp_path / ".github" / "workflows" / "release.yml"
    assert workflow.exists()

    _cli("component", "uninstall", "release", project=tmp_path)
    assert not workflow.exists()


def test_uninstall_preserves_create_if_missing_without_flag(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    _cli("component", "install", "agent-jobs", project=tmp_path)
    skill = tmp_path / ".audiagentic" / "skills" / "ag-review" / "skill.md"
    marker = tmp_path / ".audiagentic" / "components" / "agent-jobs.yaml"
    assert skill.exists()
    assert marker.exists()

    _cli("component", "uninstall", "agent-jobs", project=tmp_path)
    assert not skill.exists()
    assert not marker.exists()


def test_uninstall_removes_configs_with_flag(tmp_path):
    _cli("component", "install", "project", project=tmp_path)
    _cli("component", "install", "agent-jobs", project=tmp_path)
    marker = tmp_path / ".audiagentic" / "components" / "agent-jobs.yaml"
    assert marker.exists()

    _cli("component", "uninstall", "agent-jobs", "--remove-configs", project=tmp_path)
    assert not marker.exists()
