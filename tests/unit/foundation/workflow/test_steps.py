"""Unit tests for workflow invocation steps.

Covers all step types: ConfirmStep, ShellStep, SequenceStep, ConditionalStep.
No subprocess calls to real system tools — ShellStep tests use echo/true/false
or a guaranteed-absent binary name so all assertions are deterministic.
"""
from __future__ import annotations

import sys

import pytest

from audiagentic.foundation.workflow.invocation.models import WorkflowAnswer, WorkflowQuestion
from audiagentic.foundation.workflow.invocation.steps import (
    ConditionalStep,
    ConfirmStep,
    PlatformOverrides,
    SelectStep,
    SequenceStep,
    ShellStep,
    _platform_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ECHO = "echo" if sys.platform != "win32" else "cmd"


def _echo_cmd(*args: str) -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("cmd", "/c", "echo", *args)
    return ("echo", *args)


def _true_cmd() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("cmd", "/c", "exit", "0")
    return ("true",)


def _false_cmd() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("cmd", "/c", "exit", "1")
    return ("false",)


def _answer(value: str) -> dict[str, WorkflowAnswer]:
    return {"confirm": WorkflowAnswer(question_id="confirm", value=value)}


# ---------------------------------------------------------------------------
# ConfirmStep
# ---------------------------------------------------------------------------


class TestConfirmStep:
    def test_plan_always_returns_planned(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?")
        result = step.plan({})
        assert result.status == "planned"

    def test_run_without_answer_returns_waiting_for_input(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?")
        result = step.run({})
        assert result.status == "waiting_for_input"
        assert isinstance(result.question, WorkflowQuestion)
        assert result.question.id == "confirm"
        assert result.question.kind == "confirm"

    def test_run_without_answer_includes_yes_no_options(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?")
        result = step.run({})
        assert result.question is not None
        ids = {opt["id"] for opt in result.question.options}
        assert ids == {"yes", "no"}

    def test_run_prompt_interpolates_context(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Delete {name}?")
        result = step.run({"name": "prod-db"})
        assert result.question is not None
        assert "prod-db" in result.question.prompt

    @pytest.mark.parametrize("value", ["yes", "y", "true", "1", "YES", "True"])
    def test_run_affirmative_answers_return_ok(self, value: str) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?")
        result = step.run({}, _answer(value))
        assert result.status == "ok"

    @pytest.mark.parametrize("value", ["no", "n", "false", "0", "NO", "cancel", ""])
    def test_run_negative_answers_return_skipped(self, value: str) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?")
        result = step.run({}, _answer(value))
        assert result.status == "skipped"
        assert result.reason == "confirmation declined"

    def test_run_uses_step_id_to_look_up_answer(self) -> None:
        step = ConfirmStep(id="my-step", prompt="Go?")
        answers = {"my-step": WorkflowAnswer(question_id="my-step", value="yes")}
        result = step.run({}, answers)
        assert result.status == "ok"

    def test_run_ignores_unrelated_answer_keys(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Go?")
        answers = {"other-step": WorkflowAnswer(question_id="other-step", value="yes")}
        result = step.run({}, answers)
        assert result.status == "waiting_for_input"

    def test_run_default_propagated_into_question(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?", default="no")
        result = step.run({})
        assert result.question is not None
        assert result.question.default == "no"

    def test_run_metadata_propagated_into_question(self) -> None:
        step = ConfirmStep(id="confirm", prompt="Proceed?", metadata={"risk": "high"})
        result = step.run({})
        assert result.question is not None
        assert result.question.metadata.get("risk") == "high"


# ---------------------------------------------------------------------------
# ShellStep
# ---------------------------------------------------------------------------


class TestShellStep:
    def test_plan_returns_planned_with_command(self) -> None:
        step = ShellStep(id="sh", command=("echo", "hello"))
        result = step.plan({})
        assert result.status == "planned"
        assert result.outputs["command"] == ["echo", "hello"]

    def test_plan_interpolates_context(self) -> None:
        step = ShellStep(id="sh", command=("echo", "{msg}"))
        result = step.plan({"msg": "world"})
        assert result.outputs["command"] == ["echo", "world"]

    def test_dry_run_returns_plan(self) -> None:
        step = ShellStep(id="sh", command=("echo", "hi"), dry_run=True)
        result = step.run({"msg": "hi"})
        assert result.status == "planned"

    def test_missing_binary_returns_failed(self) -> None:
        step = ShellStep(id="sh", command=("__no_such_binary_xyz__", "arg"))
        result = step.run({})
        assert result.status == "failed"
        assert "__no_such_binary_xyz__" in (result.reason or "")

    def test_successful_command_returns_ok(self) -> None:
        step = ShellStep(id="sh", command=_true_cmd())
        result = step.run({})
        assert result.status == "ok"
        assert result.outputs["returncode"] == 0

    def test_failing_command_returns_failed(self) -> None:
        step = ShellStep(id="sh", command=_false_cmd())
        result = step.run({})
        assert result.status == "failed"
        assert result.outputs["returncode"] != 0

    @pytest.mark.skipif(sys.platform == "win32", reason="echo stdout capture not tested on win32")
    def test_stdout_captured_in_outputs(self) -> None:
        step = ShellStep(id="sh", command=("echo", "hello world"))
        result = step.run({})
        assert result.status == "ok"
        assert "hello world" in result.outputs["stdout"]

    def test_command_interpolates_context_at_run(self) -> None:
        step = ShellStep(id="sh", command=_echo_cmd("{greeting}"))
        result = step.run({"greeting": "hi"})
        assert result.status == "ok"

    def test_timeout_produces_failed_result(self) -> None:
        if sys.platform == "win32":
            cmd = ("ping", "-n", "10", "127.0.0.1")
        else:
            cmd = ("sleep", "10")
        step = ShellStep(id="sh", command=cmd, timeout=1)
        result = step.run({})
        assert result.status == "failed"
        assert "timed out" in (result.reason or "")

    def test_render_command_interpolates_all_parts(self) -> None:
        step = ShellStep(id="sh", command=("{bin}", "{sub}", "{arg}"))
        rendered = step._render_command({"bin": "git", "sub": "commit", "arg": "-m"})
        assert rendered == ("git", "commit", "-m")


# ---------------------------------------------------------------------------
# SequenceStep
# ---------------------------------------------------------------------------


class TestSequenceStep:
    def _make_confirm(self, step_id: str, answer: str | None = "yes") -> tuple[ConfirmStep, dict]:
        step = ConfirmStep(id=step_id, prompt="Go?")
        answers = (
            {step_id: WorkflowAnswer(question_id=step_id, value=answer)}
            if answer is not None
            else {}
        )
        return step, answers

    def test_plan_calls_plan_on_all_children(self) -> None:
        s1 = ShellStep(id="a", command=("echo", "a"))
        s2 = ShellStep(id="b", command=("echo", "b"))
        seq = SequenceStep(id="seq", steps=(s1, s2))
        result = seq.plan({})
        assert result.status == "planned"
        assert "a" in result.outputs
        assert "b" in result.outputs

    def test_run_all_ok_returns_ok(self) -> None:
        s1 = ShellStep(id="a", command=_true_cmd())
        s2 = ShellStep(id="b", command=_true_cmd())
        seq = SequenceStep(id="seq", steps=(s1, s2))
        result = seq.run({})
        assert result.status == "ok"

    def test_run_fail_fast_stops_at_first_failure(self) -> None:
        s_fail = ShellStep(id="fail", command=_false_cmd())
        s_ok = ShellStep(id="ok", command=_true_cmd())
        seq = SequenceStep(id="seq", steps=(s_fail, s_ok), fail_fast=True)
        result = seq.run({})
        assert result.status == "failed"
        assert "fail" in result.outputs
        assert "ok" not in result.outputs

    def test_run_no_fail_fast_runs_all_steps(self) -> None:
        s_fail = ShellStep(id="fail", command=_false_cmd())
        s_ok = ShellStep(id="ok", command=_true_cmd())
        seq = SequenceStep(id="seq", steps=(s_fail, s_ok), fail_fast=False)
        result = seq.run({})
        assert "fail" in result.outputs
        assert "ok" in result.outputs

    def test_run_propagates_waiting_for_input_when_fail_fast(self) -> None:
        confirm = ConfirmStep(id="confirm", prompt="Go?")
        s_ok = ShellStep(id="ok", command=_true_cmd())
        seq = SequenceStep(id="seq", steps=(confirm, s_ok), fail_fast=True)
        result = seq.run({}, {})
        assert result.status == "waiting_for_input"
        assert result.question is not None

    def test_run_skipped_step_stops_sequence_when_fail_fast(self) -> None:
        confirm, answers = self._make_confirm("confirm", answer="no")
        s_ok = ShellStep(id="ok", command=_true_cmd())
        seq = SequenceStep(id="seq", steps=(confirm, s_ok), fail_fast=True)
        result = seq.run({}, answers)
        assert result.status == "skipped"
        assert "ok" not in result.outputs

    def test_run_empty_steps_returns_ok(self) -> None:
        seq = SequenceStep(id="seq", steps=())
        result = seq.run({})
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# ConditionalStep
# ---------------------------------------------------------------------------


class TestConditionalStep:
    def test_plan_always_returns_planned(self) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.plan({})
        assert result.status == "planned"

    def test_run_true_condition_executes_when_true(self) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.run({"flag": True})
        assert result.status == "ok"

    def test_run_false_condition_with_when_false_executes_it(self) -> None:
        when_true = ShellStep(id="t", command=_false_cmd())
        when_false = ShellStep(id="f", command=_true_cmd())
        step = ConditionalStep(
            id="cond", condition_key="flag", when_true=when_true, when_false=when_false
        )
        result = step.run({"flag": False})
        assert result.status == "ok"

    def test_run_false_condition_without_when_false_returns_skipped(self) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.run({"flag": False})
        assert result.status == "skipped"
        assert result.reason is not None

    def test_run_missing_key_treated_as_false(self) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.run({})
        assert result.status == "skipped"

    @pytest.mark.parametrize("truthy", [1, "yes", [1], {"a": 1}])
    def test_run_truthy_context_value_executes_when_true(self, truthy: object) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.run({"flag": truthy})
        assert result.status == "ok"

    @pytest.mark.parametrize("falsy", [0, "", [], {}, None])
    def test_run_falsy_context_value_skips(self, falsy: object) -> None:
        when_true = ShellStep(id="t", command=_true_cmd())
        step = ConditionalStep(id="cond", condition_key="flag", when_true=when_true)
        result = step.run({"flag": falsy})
        assert result.status == "skipped"

    def test_run_passes_answers_through_to_inner_step(self) -> None:
        inner = ConfirmStep(id="inner", prompt="Go?")
        answers = {"inner": WorkflowAnswer(question_id="inner", value="yes")}
        step = ConditionalStep(id="cond", condition_key="flag", when_true=inner)
        result = step.run({"flag": True}, answers)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# PlatformOverrides on ShellStep (RV01/RV02)
# ---------------------------------------------------------------------------


class TestPlatformOverrides:
    def test_resolve_returns_current_platform_command(self) -> None:
        overrides = PlatformOverrides(
            win=("cmd", "/c", "ver"), darwin=("sw_vers",), linux=("uname",)
        )
        assert overrides.resolve(_platform_key()) is not None

    def test_resolve_explicit_key(self) -> None:
        overrides = PlatformOverrides(win=("w",), linux=("l",))
        assert overrides.resolve("win") == ("w",)
        assert overrides.resolve("linux") == ("l",)
        assert overrides.resolve("darwin") is None

    def test_shellstep_uses_override_for_current_platform(self) -> None:
        key = _platform_key()
        override_cmd = _echo_cmd("from-override")
        step = ShellStep(
            id="sh",
            command=("__base_should_not_run__",),
            platform=PlatformOverrides(**{key: override_cmd}),
        )
        rendered = step._render_command({})
        assert rendered == override_cmd

    def test_shellstep_falls_back_to_base_when_no_override(self) -> None:
        # Build overrides for platforms other than the current one.
        others = {k: ("x",) for k in ("win", "darwin", "linux") if k != _platform_key()}
        step = ShellStep(
            id="sh", command=("base", "cmd"), platform=PlatformOverrides(**others)
        )
        assert step._render_command({}) == ("base", "cmd")

    def test_override_still_interpolates_context(self) -> None:
        key = _platform_key()
        step = ShellStep(
            id="sh",
            command=("base",),
            platform=PlatformOverrides(**{key: ("tool", "{arg}")}),
        )
        assert step._render_command({"arg": "v"}) == ("tool", "v")


# ---------------------------------------------------------------------------
# SequenceStep exposes prior results for conditional branching (RV02)
# ---------------------------------------------------------------------------


class TestSequenceStepResults:
    def test_later_step_can_branch_on_prior_status(self) -> None:
        recorded: dict[str, object] = {}

        def _select(context: dict) -> str | None:
            recorded["status"] = dict(context.get("step_status", {}))
            recorded["results"] = dict(context.get("step_results", {}))
            return "run"

        probe = ShellStep(id="probe", command=_true_cmd())
        gated = SelectStep(
            id="gated",
            select=_select,
            variants={"run": ShellStep(id="inner", command=_true_cmd())},
        )
        seq = SequenceStep(id="seq", steps=(probe, gated))
        result = seq.run({})
        assert result.status == "ok"
        assert recorded["status"].get("probe") == "ok"
        assert "probe" in recorded["results"]
