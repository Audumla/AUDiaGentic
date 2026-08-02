"""Subprocess-level CLI test for --component-profile (CP07/RV127).

Exercises the real audiagentic entrypoint the way a user invokes it —
flag parsing, env propagation, loader profile layering — asserting on
actual stdout and exit code rather than in-process registry state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROFILE_COMPONENT_YAML = """\
type: component
id: cli-profile-component
display-name: CLI Profile Component
description: Fixture component loaded only under the test profile
detection-marker: .audiagentic/components/cli-profile-component.yaml
"""


def _run_cli(args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    code = "import sys; from audiagentic.launcher import main; sys.exit(main(sys.argv[1:]))"
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["AUDIAGENTIC_HOME"] = str(tmp_path / "home")
    env["AUDIAGENTIC_REPO_ROOT"] = str(tmp_path)
    env.pop("AUDIAGENTIC_COMPONENT_PROFILE", None)
    env.pop("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", None)
    src = Path(__file__).resolve().parents[3] / "src"
    root = Path(__file__).resolve().parents[3]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(src), str(root), existing) if p)
    return env


def test_component_list_includes_profile_component(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".audiagentic" / "cli-test-profile" / "components"
    profile_dir.mkdir(parents=True)
    (profile_dir / "cli-profile-component.yaml").write_text(
        PROFILE_COMPONENT_YAML, encoding="utf-8"
    )

    result = _run_cli(
        ["--component-profile", "cli-test-profile", "component", "list"],
        cwd=tmp_path,
        env=_base_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    ids = {row["component_id"] for row in rows}
    assert "cli-profile-component" in ids, ids
    # Base components must layer underneath the profile, not be replaced.
    assert "session" in ids, ids


def test_component_list_without_profile_excludes_profile_component(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".audiagentic" / "cli-test-profile" / "components"
    profile_dir.mkdir(parents=True)
    (profile_dir / "cli-profile-component.yaml").write_text(
        PROFILE_COMPONENT_YAML, encoding="utf-8"
    )

    result = _run_cli(
        ["component", "list"],
        cwd=tmp_path,
        env=_base_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    ids = {row["component_id"] for row in rows}
    assert "cli-profile-component" not in ids, ids
    assert "session" in ids, ids


def test_component_profile_with_project_sets_repo_root_from_unrelated_cwd(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    unrelated_cwd = tmp_path / "elsewhere"
    profile_dir = project_root / ".audiagentic" / "cli-test-profile" / "components"
    profile_dir.mkdir(parents=True)
    unrelated_cwd.mkdir()
    (profile_dir / "cli-profile-component.yaml").write_text(
        PROFILE_COMPONENT_YAML, encoding="utf-8"
    )
    env = _base_env(project_root)
    env.pop("AUDIAGENTIC_REPO_ROOT", None)

    result = _run_cli(
        [
            "--project",
            str(project_root),
            "--component-profile",
            "cli-test-profile",
            "component",
            "list",
        ],
        cwd=unrelated_cwd,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    ids = {row["component_id"] for row in rows}
    assert "cli-profile-component" in ids, ids
    assert "session" in ids, ids
