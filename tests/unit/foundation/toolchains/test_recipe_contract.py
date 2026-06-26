from __future__ import annotations

from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)


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


def test_recipe_result_helpers():
    ok = RecipeResult.ok(RecipeState.VERIFIED, artifacts=["a"], status="done")
    assert ok.success and ok.artifacts_owned == ["a"]
    bad = RecipeResult.fail("nope")
    assert not bad.success and bad.state is RecipeState.ERROR
