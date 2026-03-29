from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.lifecycle.cutover import apply_cutover
from tests.helpers import sandbox as sandbox_helper


def test_cutover_renames_workflow_and_writes_report(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "cutover")
    try:
        legacy_release = sandbox.repo / "docs" / "releases"
        legacy_release.mkdir(parents=True)
        (legacy_release / "CHANGELOG.md").write_text("legacy", encoding="utf-8")
        legacy_workflow = sandbox.repo / ".github" / "workflows"
        legacy_workflow.mkdir(parents=True)
        (legacy_workflow / "release-please.yml").write_text("workflow", encoding="utf-8")

        result = apply_cutover(sandbox.repo)
        assert result["status"] == "success"
        assert (sandbox.repo / ".audiagentic" / "installed.json").is_file()
        assert (sandbox.repo / ".github" / "workflows" / "release-please.legacy.yml").is_file()
        report = sandbox.repo / ".audiagentic" / "runtime" / "migration" / "report.json"
        assert report.is_file()
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["outcomes"]
    finally:
        sandbox.cleanup()


def test_cutover_rejects_non_legacy_state(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "cutover-invalid")
    try:
        (sandbox.repo / ".audiagentic").mkdir(parents=True)
        (sandbox.repo / ".audiagentic" / "project.yaml").write_text("contract-version: v1", encoding="utf-8")
        try:
            apply_cutover(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
