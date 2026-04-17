from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from audiagentic.planning.app.api import PlanningAPI

ROOT = Path(__file__).resolve().parents[3]
PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"


def _seed_planning_project(root: Path) -> None:
    config_dir = root / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)


def _make_inconsistent_project(root: Path) -> tuple[str, str]:
    _seed_planning_project(root)
    propagation_path = root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml"
    config = yaml.safe_load(propagation_path.read_text(encoding="utf-8"))
    config.setdefault("global", {})["enabled"] = False
    propagation_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    api = PlanningAPI(root)
    request = api.new("request", label="Req", summary="Req", source="test")
    spec = api.new("spec", label="Spec", summary="Spec", request_refs=[request.data["id"]])
    plan = api.new("plan", label="Plan", summary="Plan", spec=spec.data["id"])
    wp = api.new("wp", label="WP", summary="WP", plan=plan.data["id"])
    task = api.new("task", label="Task", summary="Task", spec=spec.data["id"])
    api.relink(wp.data["id"], "task_refs", task.data["id"])
    api.state(task.data["id"], "ready")
    api.state(task.data["id"], "in_progress")
    return wp.data["id"], task.data["id"]


def test_tm_audit_reports_inconsistencies(tmp_path: Path) -> None:
    wp_id, task_id = _make_inconsistent_project(tmp_path)

    result = subprocess.run(
        [sys.executable, "tools/planning/tm.py", "--root", str(tmp_path), "audit"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["issues_found"] > 0
    assert any(finding["id"] == task_id for finding in payload["findings"])
    api = PlanningAPI(tmp_path)
    assert api.lookup(wp_id).data["state"] == "draft"


def test_tm_audit_fix_repairs_and_logs(tmp_path: Path) -> None:
    wp_id, _ = _make_inconsistent_project(tmp_path)

    result = subprocess.run(
        [sys.executable, "tools/planning/tm.py", "--root", str(tmp_path), "audit", "--fix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["fixes_applied"] > 0
    log_path = tmp_path / ".audiagentic" / "planning" / "meta" / "propagation_log.json"
    assert log_path.exists()
    log_entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert any(entry.get("fixed_by_audit") for entry in log_entries)
    api = PlanningAPI(tmp_path)
    assert api.lookup(wp_id).data["state"] == "ready"
