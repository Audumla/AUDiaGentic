from __future__ import annotations

from typing import Any

import pytest

from audiagentic.foundation.toolchains.provision_steps import (
    CompensatingSequence,
)
from audiagentic.foundation.workflow.invocation.models import StepResult


class _FakeStep:
    """Minimal ProvisionStep mock for testing CompensatingSequence."""

    def __init__(
        self,
        step_id: str,
        run_status: str = "ok",
        revert_status: str = "ok",
        dry_run_status: str = "planned",
        run_raises: Exception | None = None,
        revert_raises: Exception | None = None,
    ) -> None:
        self.id = step_id
        self._run_status = run_status
        self._revert_status = revert_status
        self._dry_run_status = dry_run_status
        self._run_raises = run_raises
        self._revert_raises = revert_raises
        self.run_called = False
        self.revert_called = False
        self.dry_run_called = False

    def run(self, context: dict[str, Any]) -> StepResult:
        self.run_called = True
        if self._run_raises:
            raise self._run_raises
        return StepResult(status=self._run_status)

    def revert(self, context: dict[str, Any]) -> StepResult:
        self.revert_called = True
        if self._revert_raises:
            raise self._revert_raises
        return StepResult(status=self._revert_status)

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        self.dry_run_called = True
        return StepResult(status=self._dry_run_status)


@pytest.fixture
def fake_step_ok():
    return _FakeStep("ok-step")


@pytest.fixture
def fake_step_skipped():
    return _FakeStep("skipped-step", run_status="skipped")


@pytest.fixture
def fake_step_fail():
    return _FakeStep("fail-step", run_status="failed")


class TestCompensatingSequenceRun:
    def test_all_ok(self, fake_step_ok):
        seq = CompensatingSequence([fake_step_ok])
        result = seq.run({})
        assert result.status == "ok"
        assert fake_step_ok.run_called

    def test_multiple_steps_ok(self):
        steps = [_FakeStep(f"s{i}") for i in range(3)]
        seq = CompensatingSequence(steps)
        result = seq.run({})
        assert result.status == "ok"
        assert all(s.run_called for s in steps)
        step_statuses = [s["status"] for s in result.outputs["steps"]]
        assert step_statuses == ["ok", "ok", "ok"]

    def test_skipped_continues_not_reverted(self):
        ok_step = _FakeStep("ok1")
        skip_step = _FakeStep("skip", run_status="skipped")
        ok2 = _FakeStep("ok2")
        seq = CompensatingSequence([ok_step, skip_step, ok2])
        result = seq.run({})
        assert result.status == "ok"
        assert ok_step.run_called
        assert skip_step.run_called
        assert ok2.run_called

    def test_failure_triggers_rollback(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2", run_status="failed")
        s3 = _FakeStep("s3")
        seq = CompensatingSequence([s1, s2, s3])
        result = seq.run({})
        assert result.status == "failed"
        assert s1.run_called
        assert s2.run_called
        assert not s3.run_called
        assert s1.revert_called

    def test_rollback_skips_non_committed(self):
        ok1 = _FakeStep("ok1")
        skip = _FakeStep("skip", run_status="skipped")
        ok2 = _FakeStep("ok2")
        fail = _FakeStep("fail", run_status="failed")
        seq = CompensatingSequence([ok1, skip, ok2, fail])
        result = seq.run({})
        assert result.status == "failed"
        assert ok1.revert_called
        assert not skip.revert_called
        assert ok2.revert_called

    def test_rollback_reverse_order(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2")
        s3 = _FakeStep("s3", run_status="failed")
        seq = CompensatingSequence([s1, s2, s3])
        result = seq.run({})
        assert result.status == "failed"
        rollback_steps = [r["id"] for r in result.outputs["steps"] if r.get("phase") == "rollback"]
        assert rollback_steps == ["s2", "s1"]

    def test_step_exception_treated_as_failure(self):
        s1 = _FakeStep("s1", run_raises=RuntimeError("boom"))
        s2 = _FakeStep("s2")
        seq = CompensatingSequence([s1, s2])
        result = seq.run({})
        assert result.status == "failed"

    def test_per_step_results_in_outputs(self):
        s1 = _FakeStep("alpha")
        s2 = _FakeStep("beta")
        seq = CompensatingSequence([s1, s2])
        result = seq.run({})
        steps = result.outputs["steps"]
        assert len(steps) == 2
        assert steps[0]["id"] == "alpha"
        assert steps[1]["id"] == "beta"


class TestCompensatingSequenceRevert:
    def test_revert_all_steps(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2")
        seq = CompensatingSequence([s1, s2])
        result = seq.revert({})
        assert result.status == "ok"
        assert s1.revert_called
        assert s2.revert_called

    def test_revert_reports_failure(self):
        s1 = _FakeStep("s1", revert_status="failed")
        s2 = _FakeStep("s2")
        seq = CompensatingSequence([s1, s2])
        result = seq.revert({})
        assert result.status == "failed"

    def test_revert_exception_logged_not_raised(self):
        s1 = _FakeStep("s1", revert_raises=ValueError("revert error"))
        s2 = _FakeStep("s2")
        seq = CompensatingSequence([s1, s2])
        result = seq.revert({})
        assert result.status == "failed"
        assert s2.revert_called


class TestCompensatingSequenceDryRun:
    def test_dry_run_all_planned(self):
        steps = [_FakeStep(f"d{i}", dry_run_status="planned") for i in range(3)]
        seq = CompensatingSequence(steps)
        result = seq.dry_run({})
        assert result.status == "ok"
        assert all(s.dry_run_called for s in steps)

    def test_dry_run_failure_stops(self):
        s1 = _FakeStep("d1", dry_run_status="planned")
        s2 = _FakeStep("d2", dry_run_status="failed")
        s3 = _FakeStep("d3", dry_run_status="planned")
        seq = CompensatingSequence([s1, s2, s3])
        result = seq.dry_run({})
        assert result.status == "failed"
        assert s1.dry_run_called
        assert s2.dry_run_called

    def test_dry_run_success_statuses(self):
        for status in ("planned", "ok", "skipped"):
            step = _FakeStep(f"d-{status}", dry_run_status=status)
            seq = CompensatingSequence([step])
            result = seq.dry_run({})
            assert result.status == "ok", f"expected ok for dry-run status {status!r}"


class TestCompensatingSequenceCustomId:
    def test_default_id(self):
        seq = CompensatingSequence([])
        assert seq.id == "compensating-sequence"

    def test_custom_id(self):
        seq = CompensatingSequence([], id="my-seq")
        assert seq.id == "my-seq"


class TestEmptySequence:
    def test_run_empty_ok(self):
        seq = CompensatingSequence([])
        result = seq.run({})
        assert result.status == "ok"

    def test_revert_empty_ok(self):
        seq = CompensatingSequence([])
        result = seq.revert({})
        assert result.status == "ok"

    def test_dry_run_empty_ok(self):
        seq = CompensatingSequence([])
        result = seq.dry_run({})
        assert result.status == "ok"
