"""CC41 Activity 4 — declarative lifecycle extensions and the mode adapter.

Covers the gaps CC41 named: dry_run, an explicit verify probe, configure steps,
and the internal plan/apply/prune/status -> lifecycle mapping. The load-bearing
assertions are the ones proving plan and status do not mutate.
"""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.probes import ProbeResult
from audiagentic.foundation.toolchains.recipe_contract import RecipeState
from audiagentic.foundation.toolchains.recipe_patterns import (
    DeclaredStepRecipe,
    InstallManifest,
    NoAutomationRecipe,
    run_recipe_mode,
)


def _echo(step_id: str, word: str) -> dict:
    """A shell step that is only ever PLANNED, never executed (dry_run)."""
    return {"type": "shell", "id": step_id, "command": ["echo", word], "dry_run": True}


def _write(step_id: str, path, content: str = "x") -> dict:
    """A step that genuinely executes and succeeds, for phases that must run."""
    return {"type": "write-file", "id": step_id, "path": str(path), "content": content}


class _RecordingProbe:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.calls = 0

    def check(self, context=None) -> ProbeResult:
        self.calls += 1
        return ProbeResult(self.passed, "recorded probe")


# ---------------------------------------------------------------------------
# 4.1 dry_run — must describe, never execute
# ---------------------------------------------------------------------------

def test_dry_run_reports_planned_commands_without_running_them(monkeypatch):
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("dry_run must not execute a subprocess")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    recipe = DeclaredStepRecipe(
        InstallManifest(install_steps=(_echo("i", "installing"),)), {}
    )
    result = recipe.dry_run({})

    assert result.success is True
    assert result.state == RecipeState.ABSENT
    assert "would run" in result.status


def test_dry_run_prefers_declared_dry_run_steps():
    recipe = DeclaredStepRecipe(
        InstallManifest(
            install_steps=(_echo("i", "install"),),
            dry_run_steps=(_echo("d", "planned"),),
        ),
        {},
    )
    result = recipe.dry_run({})
    assert any("planned" in a for a in result.artifacts_owned)
    assert not any("install" in a for a in result.artifacts_owned)


def test_dry_run_respects_the_verification_gate():
    recipe = DeclaredStepRecipe(
        InstallManifest(
            install_steps=(_echo("i", "x"),),
            verified=False,
            source_label="unconfirmed",
            gate_action="verify the source",
        ),
        {},
    )
    result = recipe.dry_run({})
    assert result.action_needed == "verify the source"


def test_dry_run_with_nothing_declared_is_a_clean_noop():
    result = DeclaredStepRecipe(InstallManifest(), {}).dry_run({})
    assert result.success is True
    assert result.status == "nothing to do"


def test_base_contract_dry_run_default_is_honest_not_a_stub():
    recipe = NoAutomationRecipe(action_needed="do it by hand")
    result = recipe.dry_run({})
    assert result.success is True


# ---------------------------------------------------------------------------
# 4.2 explicit verify probe
# ---------------------------------------------------------------------------

def test_verify_uses_declared_probe_over_status_command():
    probe = _RecordingProbe(passed=True)
    recipe = DeclaredStepRecipe(
        InstallManifest(status_command="never-run --version", verify_probe=probe), {}
    )
    result = recipe.verify({})

    assert probe.calls == 1
    assert result.state == RecipeState.VERIFIED


def test_verify_probe_failure_reports_absent_not_crash():
    recipe = DeclaredStepRecipe(
        InstallManifest(verify_probe=_RecordingProbe(passed=False)), {}
    )
    assert recipe.verify({}).state == RecipeState.ABSENT


def test_verify_falls_back_when_no_probe_declared():
    recipe = DeclaredStepRecipe(InstallManifest(), {})
    assert recipe.verify({}).state == RecipeState.VERIFIED


# ---------------------------------------------------------------------------
# 4.3 configure steps
# ---------------------------------------------------------------------------

def test_configure_runs_declared_steps(tmp_path):
    target = tmp_path / "configured.txt"
    recipe = DeclaredStepRecipe(
        InstallManifest(configure_steps=(_write("c", target, "written"),)), {}
    )
    result = recipe.configure({})

    assert result.success is True
    assert result.state == RecipeState.CONFIGURING
    assert target.read_text(encoding="utf-8") == "written"  # the phase really ran


def test_configure_without_steps_stays_a_noop():
    result = DeclaredStepRecipe(InstallManifest(), {}).configure({})
    assert result.status == "no config write needed"


def test_configure_refuses_when_source_unverified(tmp_path):
    target = tmp_path / "must-not-exist.txt"
    recipe = DeclaredStepRecipe(
        InstallManifest(
            configure_steps=(_write("c", target),),
            verified=False,
            source_label="unconfirmed",
            gate_action="verify first",
        ),
        {},
    )
    result = recipe.configure({})

    assert result.success is False
    assert result.action_needed == "verify first"
    assert not target.exists()  # the gate held: nothing was written


def test_provision_steps_include_configure_phase():
    recipe = DeclaredStepRecipe(
        InstallManifest(
            install_steps=(_echo("i", "a"),), configure_steps=(_echo("c", "b"),)
        ),
        {},
    )
    assert len(recipe.provision_steps()) == 2


# ---------------------------------------------------------------------------
# 4.5 mode adapter — the public seam
# ---------------------------------------------------------------------------

def test_mode_adapter_maps_each_public_mode_to_its_lifecycle():
    seen: list[str] = []

    class _Spy(DeclaredStepRecipe):
        def provision(self, context):  # apply
            seen.append("provision")
            return super().dry_run(context)

        def dry_run(self, context):  # plan
            seen.append("dry_run")
            return super().dry_run(context)

        def uninstall(self, context):  # prune
            seen.append("uninstall")
            return super().dry_run(context)

        def verify(self, context):  # status
            seen.append("verify")
            return super().dry_run(context)

    recipe = _Spy(InstallManifest(), {})
    for mode in ("plan", "apply", "prune", "status", "upgrade"):
        run_recipe_mode(recipe, mode, {})

    assert seen == ["dry_run", "provision", "uninstall", "verify"]


def test_upgrade_is_explicit_and_not_applicable_by_default():
    recipe = DeclaredStepRecipe(InstallManifest(), {})

    result = run_recipe_mode(recipe, "upgrade", {})

    assert result.success is True
    assert result.state is RecipeState.NOT_APPLICABLE


def test_declared_step_recipe_runs_only_explicit_upgrade_steps(tmp_path):
    target = tmp_path / "upgraded.txt"
    recipe = DeclaredStepRecipe(
        InstallManifest(upgrade_steps=(_write("upgrade", target, "done"),)), {}
    )

    result = run_recipe_mode(recipe, "upgrade", {})

    assert result.success is True
    assert result.state is RecipeState.UPGRADED
    assert target.read_text(encoding="utf-8") == "done"


def test_mode_adapter_rejects_an_unsupported_mode():
    recipe = DeclaredStepRecipe(InstallManifest(), {})
    with pytest.raises(AudiaGenticError) as excinfo:
        run_recipe_mode(recipe, "repair", {})
    assert excinfo.value.code == "CON-RCP-001"


@pytest.mark.parametrize("mode", ["plan", "status"])
def test_query_modes_never_execute(monkeypatch, mode):
    """plan and status are queries — the RV497 defect must not reappear here."""
    import subprocess

    def _boom(*a, **k):
        raise AssertionError(f"{mode} must not execute a subprocess")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    recipe = DeclaredStepRecipe(
        InstallManifest(
            install_steps=(_echo("i", "x"),),
            verify_probe=_RecordingProbe(passed=True),
        ),
        {},
    )
    result = run_recipe_mode(recipe, mode, {})
    assert result.success is True
