from __future__ import annotations

from typing import Any

import pytest

from audiagentic.foundation.steps import SequenceStep, StepResult


class _FakeStep:
    """Minimal step mock for testing SequenceStep with compensation."""

    def __init__(
        self,
        step_id: str,
        run_status: str = "ok",
        compensate_status: str = "ok",
        plan_status: str = "planned",
        run_raises: Exception | None = None,
        compensate_raises: Exception | None = None,
    ) -> None:
        self.id = step_id
        self._run_status = run_status
        self._compensate_status = compensate_status
        self._plan_status = plan_status
        self._run_raises = run_raises
        self._compensate_raises = compensate_raises
        self.run_called = False
        self.compensate_called = False
        self.plan_called = False

    def run(self, context: dict[str, Any]) -> StepResult:
        self.run_called = True
        if self._run_raises:
            raise self._run_raises
        return StepResult(status=self._run_status)

    def plan(self, context: dict[str, Any]) -> StepResult:
        self.plan_called = True
        return StepResult(status=self._plan_status)

    def compensate(self, context: dict[str, Any]) -> StepResult:
        self.compensate_called = True
        if self._compensate_raises:
            raise self._compensate_raises
        return StepResult(status=self._compensate_status)


@pytest.fixture
def fake_step_ok():
    return _FakeStep("ok-step")


@pytest.fixture
def fake_step_skipped():
    return _FakeStep("skipped-step", run_status="skipped")


@pytest.fixture
def fake_step_fail():
    return _FakeStep("fail-step", run_status="failed")


class TestSequenceStepRun:
    def test_all_ok(self, fake_step_ok):
        seq = SequenceStep([fake_step_ok], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "ok"
        assert fake_step_ok.run_called

    def test_multiple_steps_ok(self):
        steps = [_FakeStep(f"s{i}") for i in range(3)]
        seq = SequenceStep(steps, compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "ok"
        assert all(s.run_called for s in steps)
        step_statuses = [s["status"] for s in result.outputs["steps"]]
        assert step_statuses == ["ok", "ok", "ok"]

    def test_skipped_with_fail_fast_returns_early(self):
        ok_step = _FakeStep("ok1")
        skip_step = _FakeStep("skip", run_status="skipped")
        ok2 = _FakeStep("ok2")
        seq = SequenceStep([ok_step, skip_step, ok2], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "skipped"
        assert ok_step.run_called
        assert skip_step.run_called
        assert not ok2.run_called

    def test_skipped_continues_with_fail_fast_false(self):
        ok_step = _FakeStep("ok1")
        skip_step = _FakeStep("skip", run_status="skipped")
        ok2 = _FakeStep("ok2")
        seq = SequenceStep([ok_step, skip_step, ok2], compensate_on_failure=True, fail_fast=False)
        result = seq.run({})
        assert result.status == "ok"
        assert ok_step.run_called
        assert skip_step.run_called
        assert ok2.run_called

    def test_failure_triggers_compensation(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2", run_status="failed")
        s3 = _FakeStep("s3")
        seq = SequenceStep([s1, s2, s3], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "failed"
        assert s1.run_called
        assert s2.run_called
        assert not s3.run_called
        assert s1.compensate_called

    def test_compensation_skips_non_committed_with_fail_fast_false(self):
        ok1 = _FakeStep("ok1")
        skip = _FakeStep("skip", run_status="skipped")
        ok2 = _FakeStep("ok2")
        fail = _FakeStep("fail", run_status="failed")
        seq = SequenceStep([ok1, skip, ok2, fail], compensate_on_failure=True, fail_fast=False)
        result = seq.run({})
        assert result.status == "failed"
        assert ok1.compensate_called
        assert not skip.compensate_called
        assert ok2.compensate_called

    def test_compensation_reverse_order(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2")
        s3 = _FakeStep("s3", run_status="failed")
        seq = SequenceStep([s1, s2, s3], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "failed"
        compensation_ids = [r["id"] for r in result.compensation]
        assert compensation_ids == ["s2", "s1"]

    def test_step_exception_treated_as_failure(self):
        s1 = _FakeStep("s1", run_raises=RuntimeError("boom"))
        s2 = _FakeStep("s2")
        seq = SequenceStep([s1, s2], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "failed"

    def test_per_step_results_in_outputs(self):
        s1 = _FakeStep("alpha")
        s2 = _FakeStep("beta")
        seq = SequenceStep([s1, s2], compensate_on_failure=True)
        result = seq.run({})
        steps = result.outputs["steps"]
        assert len(steps) == 2
        assert steps[0]["id"] == "alpha"
        assert steps[1]["id"] == "beta"


class TestSequenceStepCompensate:
    def test_compensate_all_steps(self):
        s1 = _FakeStep("s1")
        s2 = _FakeStep("s2")
        seq = SequenceStep([s1, s2], compensate_on_failure=True)
        result = seq.compensate({})
        assert result.status == "ok"
        assert s1.compensate_called
        assert s2.compensate_called

    def test_compensate_reports_failure(self):
        s1 = _FakeStep("s1", compensate_status="failed")
        s2 = _FakeStep("s2")
        seq = SequenceStep([s1, s2], compensate_on_failure=True)
        result = seq.compensate({})
        assert result.status == "failed"

    def test_compensate_exception_logged_not_raised(self):
        s1 = _FakeStep("s1", compensate_raises=ValueError("compensation error"))
        s2 = _FakeStep("s2")
        seq = SequenceStep([s1, s2], compensate_on_failure=True)
        result = seq.compensate({})
        assert result.status == "failed"
        assert s2.compensate_called


class TestSequenceStepPlan:
    def test_plan_all_planned(self):
        steps = [_FakeStep(f"d{i}", plan_status="planned") for i in range(3)]
        seq = SequenceStep(steps, compensate_on_failure=True)
        result = seq.plan({})
        assert result.status == "planned"
        assert all(s.plan_called for s in steps)

    def test_plan_failure_stops(self):
        s1 = _FakeStep("d1", plan_status="planned")
        s2 = _FakeStep("d2", plan_status="failed")
        s3 = _FakeStep("d3", plan_status="planned")
        seq = SequenceStep([s1, s2, s3], compensate_on_failure=True)
        result = seq.plan({})
        assert result.status == "failed"
        assert s1.plan_called
        assert s2.plan_called

    def test_plan_success_statuses(self):
        for status in ("planned", "ok", "skipped"):
            step = _FakeStep(f"d-{status}", plan_status=status)
            seq = SequenceStep([step], compensate_on_failure=True)
            result = seq.plan({})
            assert result.status == "planned", f"expected planned for plan status {status!r}"


class TestSequenceStepCustomId:
    def test_default_id(self):
        seq = SequenceStep([])
        assert seq.id == "sequence"

    def test_custom_id(self):
        seq = SequenceStep([], id="my-seq")
        assert seq.id == "my-seq"


class TestEmptySequence:
    def test_run_empty_ok(self):
        seq = SequenceStep([], compensate_on_failure=True)
        result = seq.run({})
        assert result.status == "ok"

    def test_compensate_empty_ok(self):
        seq = SequenceStep([], compensate_on_failure=True)
        result = seq.compensate({})
        assert result.status == "ok"

    def test_plan_empty_ok(self):
        seq = SequenceStep([], compensate_on_failure=True)
        result = seq.plan({})
        assert result.status == "planned"
