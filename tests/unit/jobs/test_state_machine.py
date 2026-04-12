from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.execution.jobs.state_machine import LEGAL_TRANSITIONS, transition_and_persist, transition_job
from audiagentic.runtime.state.jobs_store import read_job_record, write_job_record
from tests.helpers import sandbox as sandbox_helper


def _fixture_job(state: str = "created") -> dict:
    fixture = json.loads(
        (ROOT / "docs" / "examples" / "fixtures" / "job-record.valid.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["state"] = state
    fixture["updated-at"] = "2026-03-29T00:00:00Z"
    fixture["created-at"] = "2026-03-29T00:00:00Z"
    return fixture


def test_state_machine_allows_legal_transitions() -> None:
    for current_state, allowed in LEGAL_TRANSITIONS.items():
        for new_state in allowed:
            updated = transition_job(_fixture_job(current_state), new_state, now_fn=lambda: "now")
            assert updated["state"] == new_state
            assert updated["updated-at"] == "now"


def test_state_machine_rejects_illegal_transition() -> None:
    record = _fixture_job("created")
    try:
        transition_job(record, "running", now_fn=lambda: "later")
    except AudiaGenticError as exc:
        assert exc.kind == "business-rule"
    else:
        raise AssertionError("expected illegal transition error")
    assert record["state"] == "created"
    assert record["updated-at"] == "2026-03-29T00:00:00Z"


def test_store_write_is_idempotent(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-store-idempotent")
    try:
        payload = build_job_record(
            job_id="job_20260330_0001",
            packet_id="pkt-job-001",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
        )
        path = write_job_record(sandbox.repo, payload)
        first = path.read_text(encoding="utf-8")
        path2 = write_job_record(sandbox.repo, payload)
        second = path2.read_text(encoding="utf-8")
        assert first == second
    finally:
        sandbox.cleanup()


def test_transition_and_persist_does_not_corrupt_on_error(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-transition-error")
    try:
        payload = _fixture_job("created")
        write_job_record(sandbox.repo, payload)
        before = read_job_record(sandbox.repo, payload["job-id"])
        try:
            transition_and_persist(sandbox.repo, payload["job-id"], "running")
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected illegal transition error")
        after = read_job_record(sandbox.repo, payload["job-id"])
        assert after == before
    finally:
        sandbox.cleanup()
