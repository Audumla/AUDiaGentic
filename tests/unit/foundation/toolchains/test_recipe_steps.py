from __future__ import annotations

from dataclasses import dataclass

from audiagentic.foundation.toolchains.recipe_contract import RecipeState
from audiagentic.foundation.toolchains.recipe_steps import StepRecipe


@dataclass
class _FakeStep:
    id: str
    status: str
    reason: str | None = None
    ran: bool = False

    def run(self, context, answers=None):
        self.ran = True
        return self


def test_probe_reports_present_and_absent():
    present = StepRecipe("r", present_check=lambda: True)
    absent = StepRecipe("r", present_check=lambda: False)
    assert present.probe({}).state is RecipeState.VERIFIED
    assert absent.probe({}).state is RecipeState.ABSENT


def test_install_runs_step_and_maps_ok():
    step = _FakeStep("install", "ok")
    recipe = StepRecipe("r", install_step=step)
    result = recipe.install({})
    assert result.success
    assert step.ran is True


def test_install_skipped_is_success():
    # skipped == probe guard found it already satisfied; not a failure.
    recipe = StepRecipe("r", install_step=_FakeStep("install", "skipped"))
    assert recipe.install({}).success


def test_install_failure_propagates_reason():
    recipe = StepRecipe("r", install_step=_FakeStep("install", "failed", reason="boom"))
    result = recipe.install({})
    assert not result.success
    assert "boom" in (result.error or "")


def test_verify_uses_presence_check():
    flips = {"v": False}
    recipe = StepRecipe("r", present_check=lambda: flips["v"])
    assert not recipe.verify({}).success
    flips["v"] = True
    assert recipe.verify({}).success


def test_provision_full_lifecycle_with_steps():
    state = {"installed": False}
    install = _FakeStep("install", "ok")

    def _present():
        return state["installed"]

    recipe = StepRecipe("r", present_check=_present, install_step=install)

    # Mark installed once install runs, so verify passes.
    orig_run = install.run

    def _run(context, answers=None):
        state["installed"] = True
        return orig_run(context, answers)

    install.run = _run  # type: ignore[method-assign]

    result = recipe.provision({})
    assert result.success
    assert result.state is RecipeState.VERIFIED


def test_provision_short_circuits_when_present():
    install = _FakeStep("install", "ok")
    recipe = StepRecipe("r", present_check=lambda: True, install_step=install)
    result = recipe.provision({})
    assert result.success
    assert install.ran is False  # never installed


def test_teardown_runs_uninstall_and_verifies_absent():
    state = {"present": True}
    uninstall = _FakeStep("uninstall", "ok")

    def _present():
        return state["present"]

    recipe = StepRecipe("r", present_check=_present, uninstall_step=uninstall)

    orig = uninstall.run

    def _run(context, answers=None):
        state["present"] = False
        return orig(context, answers)

    uninstall.run = _run  # type: ignore[method-assign]

    result = recipe.teardown({})
    assert result.success
    assert result.state is RecipeState.ABSENT
