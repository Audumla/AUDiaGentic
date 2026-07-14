from audiagentic.foundation.steps import SequenceStep, StepResult


class _TypeErrorStep:
    id = "type-error"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, context: dict, answers=None) -> StepResult:
        self.calls += 1
        raise TypeError("inside step")

    def plan(self, context: dict) -> StepResult:
        return StepResult(status="planned")


def test_type_error_inside_step_does_not_retry() -> None:
    step = _TypeErrorStep()
    result = SequenceStep((step,)).run({})
    assert result.status == "failed"
    assert result.reason == "inside step"
    assert step.calls == 1
