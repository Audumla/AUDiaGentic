from __future__ import annotations

from audiagentic.foundation.steps import SequenceStep, StepResult


class _Step:
    def __init__(self, step_id: str, status: str = "ok", *, compensation_status: str = "ok") -> None:
        self.id = step_id
        self.status = status
        self.compensation_status = compensation_status
        self.events: list[str] = []

    def run(self, context: dict) -> StepResult:
        self.events.append(f"run:{self.id}")
        return StepResult(status=self.status, reason="primary failure" if self.status == "failed" else None)

    def plan(self, context: dict) -> StepResult:
        return StepResult(status="planned")

    def compensate(self, context: dict) -> StepResult:
        self.events.append(f"compensate:{self.id}")
        return StepResult(status=self.compensation_status, reason="rollback failure" if self.compensation_status == "failed" else None)


def test_sequence_compensates_successes_in_reverse_without_masking_primary() -> None:
    one, two, fail = _Step("one"), _Step("two", compensation_status="failed"), _Step("fail", "failed")
    result = SequenceStep((one, two, fail), compensate_on_failure=True).run({})
    assert result.status == "failed"
    assert result.reason == "primary failure"
    assert [entry["id"] for entry in result.compensation] == ["two", "one"]
    assert result.compensation[0]["status"] == "failed"


def test_sequence_plan_is_side_effect_free() -> None:
    step = _Step("one")
    result = SequenceStep((step,)).plan({})
    assert result.status == "planned"
    assert step.events == []
