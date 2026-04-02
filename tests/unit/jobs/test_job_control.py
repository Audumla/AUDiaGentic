from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.jobs import control as job_control


def test_build_job_control_request_requires_supported_action() -> None:
    payload = job_control.build_job_control_request(
        job_id="job_20260330_0001",
        project_id="my-project",
        requested_action="cancel",
        requested_by="operator",
        reason="stop now",
        requested_at="2026-03-30T00:00:00Z",
    )
    assert payload["result"] == "pending"
    assert payload["requested-action"] == "cancel"


def test_build_job_control_request_rejects_unknown_action() -> None:
    try:
        job_control.build_job_control_request(
            job_id="job_20260330_0001",
            project_id="my-project",
            requested_action="pause",
            requested_by="operator",
            reason="stop now",
        )
    except Exception as exc:  # noqa: BLE001
        assert "unsupported job control action" in str(exc)
    else:
        raise AssertionError("expected validation failure")
