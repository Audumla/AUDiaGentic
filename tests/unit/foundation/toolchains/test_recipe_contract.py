from __future__ import annotations

from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.workflow.invocation.models import StepResult


class _Recipe(ProvisioningRecipe):
    """Minimal recipe that records lifecycle calls for assertions."""

    def __init__(self, *, already_present=False, fail_at=None):
        super().__init__()
        self.calls: list[str] = []
        self.already_present = already_present
        self.fail_at = fail_at

    def probe(self, context):
        self.calls.append("probe")
        state = RecipeState.VERIFIED if self.already_present else RecipeState.ABSENT
        return RecipeResult.ok(state)

    def _step(self, name, state, artifact):
        self.calls.append(name)
        if self.fail_at == name:
            return RecipeResult.fail(f"{name} failed")
        return RecipeResult.ok(state, artifacts=[artifact])

    def install(self, context):
        return self._step("install", RecipeState.INSTALLING, "bin")

    def configure(self, context):
        return self._step("configure", RecipeState.CONFIGURING, "cfg::key")

    def verify(self, context):
        self.calls.append("verify")
        return RecipeResult.ok(RecipeState.VERIFIED)

    def uninstall(self, context):
        return self._step("uninstall", RecipeState.ABSENT, "bin")

    def prune(self, context):
        return self._step("prune", RecipeState.ABSENT, "cfg::key")


class _ProvisionStep:
    def __init__(self, step_id: str, status: str = "ok") -> None:
        self.id = step_id
        self.status = status
        self.run_called = False
        self.revert_called = False

    def run(self, context):
        self.run_called = True
        return StepResult(status=self.status, reason=f"{self.id} failed" if self.status == "failed" else None)

    def revert(self, context):
        self.revert_called = True
        return StepResult(status="ok")

    def dry_run(self, context):
        return StepResult(status="planned")


class _StructuredRecipe(_Recipe):
    def __init__(self, *, steps, already_present=False):
        super().__init__(already_present=already_present)
        self._steps = steps

    def provision_steps(self):
        self.calls.append("provision_steps")
        return self._steps


def test_provision_runs_full_lifecycle():
    r = _Recipe()
    result = r.provision({})
    assert result.success
    assert result.state is RecipeState.VERIFIED
    assert r.calls == ["probe", "install", "configure", "verify"]
    assert "bin" in result.artifacts_owned
    assert "cfg::key" in result.artifacts_owned


def test_provision_short_circuits_when_present():
    r = _Recipe(already_present=True)
    result = r.provision({})
    assert result.success
    assert r.calls == ["probe"]  # no install/configure/verify
    assert "already" in result.status


def test_provision_stops_on_install_failure():
    r = _Recipe(fail_at="install")
    result = r.provision({})
    assert not result.success
    assert r.calls == ["probe", "install"]


def test_provision_collects_partial_artifacts_on_failure():
    r = _Recipe(fail_at="configure")
    result = r.provision({})
    assert not result.success
    assert "bin" in result.artifacts_owned  # install's artifact retained for cleanup


def test_structured_provision_uses_steps_then_verify():
    step = _ProvisionStep("install")
    r = _StructuredRecipe(steps=[step])

    result = r.provision({})

    assert result.success
    assert step.run_called
    assert r.calls == ["probe", "provision_steps", "verify"]


def test_structured_provision_short_circuits_when_present():
    step = _ProvisionStep("install")
    r = _StructuredRecipe(steps=[step], already_present=True)

    result = r.provision({})

    assert result.success
    assert not step.run_called
    assert r.calls == ["probe"]


def test_structured_provision_failure_rolls_back_and_skips_verify():
    ok = _ProvisionStep("ok")
    fail = _ProvisionStep("fail", status="failed")
    r = _StructuredRecipe(steps=[ok, fail])

    result = r.provision({})

    assert not result.success
    assert ok.revert_called
    assert r.calls == ["probe", "provision_steps"]
    assert "steps" in result.details


def test_custom_cleanup_hooks_run_on_teardown():
    r = _Recipe(already_present=True)
    ran = []
    r.custom_cleanup_hooks.append(lambda ctx: ran.append("hook"))

    # teardown: prune -> uninstall -> hooks -> post_uninstall_verify
    # post_uninstall_verify re-probes; force absent so it succeeds
    r.already_present = False
    result = r.teardown({})
    assert ran == ["hook"]
    assert result.success
    assert result.state is RecipeState.ABSENT


def test_teardown_reports_cleanup_hook_failure():
    r = _Recipe()

    def _boom(ctx):
        raise RuntimeError("api down")

    r.custom_cleanup_hooks.append(_boom)
    result = r.teardown({})
    assert not result.success
    assert "api down" in (result.error or "")


def test_cleanup_hook_failure_details_are_safe():
    """Contract layer does NOT redact secret-shaped strings — that's RS16's job.

    This test locks the division of responsibility: the contract captures
    str(exc) verbatim in result.error. Redaction happens at the shell-output
    boundary (RS16), not inside the recipe contract.
    """
    r = _Recipe()
    fake_token = "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def _boom(ctx):
        raise RuntimeError(fake_token)

    r.custom_cleanup_hooks.append(_boom)
    result = r.teardown({})
    assert not result.success
    assert fake_token in (result.error or "")


def test_recipe_result_helpers():
    ok = RecipeResult.ok(RecipeState.VERIFIED, artifacts=["a"], status="done")
    assert ok.success and ok.artifacts_owned == ["a"]
    bad = RecipeResult.fail("nope")
    assert not bad.success and bad.state is RecipeState.ERROR


class _StampingRecipe(_Recipe):
    """Records every result routed through to_result (HM20 hook)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stamped: list[RecipeResult] = []

    def to_result(self, base):
        self.stamped.append(base)
        return base


def test_to_result_routes_every_provision_return():
    # idempotent skip
    r = _StampingRecipe(already_present=True)
    r.provision({})
    assert len(r.stamped) == 1

    # full lifecycle
    r = _StampingRecipe()
    r.provision({})
    assert len(r.stamped) == 1

    # install failure
    r = _StampingRecipe(fail_at="install")
    r.provision({})
    assert len(r.stamped) == 1


def test_to_result_routes_teardown_and_post_verify():
    r = _StampingRecipe()
    result = r.teardown({})
    assert result.success
    assert len(r.stamped) == 1  # post_uninstall_verify's result

    r = _StampingRecipe(fail_at="prune")
    r.teardown({})
    assert len(r.stamped) == 1  # prune failure routed


def test_provision_via_steps_false_forces_primitive_path():
    step = _ProvisionStep("install")

    class _IntrospectionOnly(_StructuredRecipe):
        provision_via_steps = False

    r = _IntrospectionOnly(steps=[step])
    result = r.provision({})

    assert result.success
    assert not step.run_called
    assert r.calls == ["probe", "install", "configure", "verify"]


def test_provision_does_not_mutate_frozen_results():
    from dataclasses import dataclass, field
    from typing import Any

    # Standalone frozen dataclass mirroring RecipeResult's fields, matching
    # how ProviderRecipeResult is defined (frozen, not a subclass).
    @dataclass(frozen=True)
    class _FrozenResult:
        success: bool = True
        state: RecipeState = RecipeState.VERIFIED
        artifacts_owned: list = field(default_factory=list)
        status: str = ""
        error: str | None = None
        details: dict[str, Any] = field(default_factory=dict)

    class _FrozenRecipe(_Recipe):
        def install(self, context):
            self.calls.append("install")
            return _FrozenResult(artifacts_owned=["bin"], state=RecipeState.INSTALLING)

        def configure(self, context):
            self.calls.append("configure")
            return _FrozenResult(
                success=(self.fail_at != "configure"),
                state=RecipeState.CONFIGURING,
                error="configure failed" if self.fail_at == "configure" else None,
            )

        def verify(self, context):
            self.calls.append("verify")
            return _FrozenResult()

    # failure path exercises replace() on the frozen result — must not raise
    r = _FrozenRecipe(fail_at="configure")
    result = r.provision({})
    assert not result.success
    assert "bin" in result.artifacts_owned

    r = _FrozenRecipe()
    result = r.provision({})
    assert result.success
    assert "bin" in result.artifacts_owned


def test_run_steps_helper_maps_sequence_result():
    from audiagentic.foundation.toolchains.recipe_contract import run_steps

    ok = run_steps([_ProvisionStep("a")], {}, ok_status="did it")
    assert ok.success and ok.status == "did it"

    bad = run_steps(
        [_ProvisionStep("a"), _ProvisionStep("b", status="failed")],
        {},
        fail_prefix="install failed",
    )
    assert not bad.success
    assert bad.error is not None and bad.error.startswith("install failed:")


def test_recipe_result_carries_action_needed():
    ok = RecipeResult.ok(
        RecipeState.ABSENT, status="skipped", action_needed="run installer manually"
    )
    assert ok.action_needed == "run installer manually"

    bad = RecipeResult.fail("blocked", action_needed="verify source first")
    assert bad.action_needed == "verify source first"

    # default is empty, never None
    assert RecipeResult.ok(RecipeState.VERIFIED).action_needed == ""


def test_action_needed_survives_orchestration_replace_paths():
    """The provision/teardown replace() adjustments must preserve action_needed."""

    class _GuidedRecipe(_Recipe):
        def install(self, context):
            self.calls.append("install")
            return RecipeResult.ok(
                RecipeState.INSTALLING, artifacts=["bin"], action_needed="restart shell"
            )

        def configure(self, context):
            self.calls.append("configure")
            # fail so provision returns the install/configure result via replace()
            return RecipeResult.fail("configure blocked", action_needed="set API key")

    r = _GuidedRecipe(fail_at="configure")
    result = r.provision({})
    assert not result.success
    # replace(result, artifacts_owned=owned) must not drop action_needed
    assert result.action_needed == "set API key"
    assert "bin" in result.artifacts_owned


def test_action_needed_propagates_through_verify_error_replace():
    """verify-failure terminal replace() (state->ERROR) keeps action_needed."""

    class _VerifyGuided(_Recipe):
        def verify(self, context):
            self.calls.append("verify")
            return RecipeResult.fail(
                "not verified", state=RecipeState.ABSENT, action_needed="check logs"
            )

    r = _VerifyGuided()
    result = r.provision({})
    assert not result.success
    assert result.state is RecipeState.ERROR  # terminal replace applied
    assert result.action_needed == "check logs"  # and preserved
