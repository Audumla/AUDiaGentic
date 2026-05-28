from __future__ import annotations

from audiagentic.foundation.workflow.invocation import (
    ConfirmStep,
    SequenceStep,
    ShellStep,
    WorkflowAnswer,
    WorkflowInvocationRunner,
)


def test_invocation_pauses_for_question() -> None:
    result = WorkflowInvocationRunner([
        ConfirmStep("confirm", "Install {package}?"),
    ]).run({"package": "demo-package"})

    assert result.status == "waiting_for_input"
    assert result.question is not None
    assert result.question.prompt == "Install demo-package?"


def test_invocation_resumes_with_answer() -> None:
    result = WorkflowInvocationRunner([
        ConfirmStep("confirm", "Install {package}?"),
    ]).run(
        {"package": "demo-package"},
        answers={"confirm": WorkflowAnswer(question_id="confirm", value="yes")},
    )

    assert result.status == "ok"


def test_invocation_skips_when_confirmation_declined() -> None:
    result = WorkflowInvocationRunner([
        ConfirmStep("confirm", "Install {package}?"),
    ]).run(
        {"package": "demo-package"},
        answers={"confirm": WorkflowAnswer(question_id="confirm", value="no")},
    )

    assert result.status == "skipped"
    assert result.reason == "confirmation declined"


def test_shell_step_plans_command() -> None:
    result = ShellStep("install", ("npm", "install", "-g", "{package}"), dry_run=True).run(
        {"package": "demo-package"}
    )

    assert result.status == "planned"
    assert result.outputs["command"] == ["npm", "install", "-g", "demo-package"]


def test_sequence_step_stops_on_failed_step() -> None:
    result = SequenceStep(
        "seq",
        (
            ShellStep("missing", ("definitely-not-a-real-command",)),
            ShellStep("later", ("also-not-run",)),
        ),
    ).run({})

    assert result.status == "failed"
    assert "missing" in result.outputs
    assert "later" not in result.outputs
