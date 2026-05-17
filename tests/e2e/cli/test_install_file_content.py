"""E2E: verify that `component install` actually places correct file content on disk.

Tests that baseline_sync lands the right files from the template root — not just that
markers are written, but that the managed files are present and non-empty.
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


# ── core-lifecycle file content ───────────────────────────────────────────────

def test_install_core_lifecycle_creates_prompt_files(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    prompt = tmp_path / ".audiagentic" / "prompts" / "ag-review" / "default.md"
    assert prompt.is_file(), f"expected prompt file at {prompt}"
    assert prompt.stat().st_size > 0


def test_install_core_lifecycle_creates_release_workflow(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    assert wf.is_file(), f"expected workflow at {wf}"
    assert "on:" in wf.read_text(encoding="utf-8") or "jobs:" in wf.read_text(encoding="utf-8")


def test_install_core_lifecycle_seeds_project_yaml(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    assert project_yaml.is_file()
    assert project_yaml.stat().st_size > 0


def test_reinstall_core_lifecycle_refreshes_required_managed(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    prompt = tmp_path / ".audiagentic" / "prompts" / "ag-review" / "default.md"
    original = prompt.read_text(encoding="utf-8")
    prompt.write_text("corrupted", encoding="utf-8")

    _cli("component", "install", "core-lifecycle", project=tmp_path)
    assert prompt.read_text(encoding="utf-8") == original


def test_reinstall_core_lifecycle_preserves_create_if_missing(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    project_yaml.write_text("contract-version: v1\nproject-id: my-project\n", encoding="utf-8")

    _cli("component", "install", "core-lifecycle", project=tmp_path)
    assert "my-project" in project_yaml.read_text(encoding="utf-8")


# ── provider surface file content ─────────────────────────────────────────────

def test_install_claude_surface_creates_claude_md(tmp_path):
    _cli("component", "install", "provider-surface-claude", project=tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.is_file(), f"expected CLAUDE.md at {claude_md}"
    assert claude_md.stat().st_size > 0


def test_install_gemini_surface_creates_gemini_md(tmp_path):
    _cli("component", "install", "provider-surface-gemini", project=tmp_path)
    gemini_md = tmp_path / "GEMINI.md"
    assert gemini_md.is_file()
    assert gemini_md.stat().st_size > 0


def test_install_codex_surface_creates_agents_md(tmp_path):
    _cli("component", "install", "provider-surface-codex", project=tmp_path)
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.is_file()
    assert agents_md.stat().st_size > 0


def test_install_agent_jobs_creates_skill_files(tmp_path):
    _cli("component", "install", "agent-jobs", project=tmp_path)
    skill = tmp_path / ".audiagentic" / "skills" / "ag-review" / "skill.md"
    assert skill.is_file(), f"expected skill file at {skill}"
    assert skill.stat().st_size > 0


# ── uninstall removes required-managed files ──────────────────────────────────

def test_uninstall_removes_required_managed_files(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    prompt_dir = tmp_path / ".audiagentic" / "prompts"
    assert prompt_dir.exists()

    _cli("component", "uninstall", "core-lifecycle", project=tmp_path)
    assert not prompt_dir.exists()


def test_uninstall_preserves_create_if_missing_without_flag(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    assert project_yaml.exists()

    _cli("component", "uninstall", "core-lifecycle", project=tmp_path)
    assert project_yaml.exists()


def test_uninstall_removes_configs_with_flag(tmp_path):
    _cli("component", "install", "core-lifecycle", project=tmp_path)
    project_yaml = tmp_path / ".audiagentic" / "config" / "project.yaml"
    assert project_yaml.exists()

    _cli("component", "uninstall", "core-lifecycle", "--remove-configs", project=tmp_path)
    assert not project_yaml.exists()
