"""Tests for reusable install-recipe patterns (SL12, SL13).

Uses fakes only — asserts the patterns are domain-neutral and free of any
component/capability imports (boundary guard).

SL13 A6: ManagedEntryRecipe and ConfigEntryTarget tests removed — those classes
were deleted (zero consumers post hindsight MCP rewire). NoAutomationRecipe and
DeclaredStepRecipe remain as multi-consumer foundation patterns.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.toolchains.recipe_contract import RecipeState
from audiagentic.foundation.toolchains.recipe_patterns import NoAutomationRecipe

# ---- NoAutomationRecipe ----------------------------------------------------

def test_no_automation_provision_is_successful_skip():
    r = NoAutomationRecipe(action_needed="set it up by hand")
    result = r.provision({})
    assert result.success and result.state is RecipeState.ABSENT
    assert result.action_needed == "set it up by hand"


def test_no_automation_probe_and_install():
    r = NoAutomationRecipe(action_needed="do X", absent_status="none here")
    assert r.probe({}).status == "none here"
    assert r.probe({}).action_needed == "do X"
    inst = r.install({})
    assert not inst.success and inst.action_needed == "do X"


def test_no_automation_uninstall_prune_noops():
    r = NoAutomationRecipe()
    assert r.uninstall({}).state is RecipeState.ABSENT
    assert r.prune({}).state is RecipeState.ABSENT


# ---- DeclaredStepRecipe ----------------------------------------------------

def _installed_marker(tmp_path):
    return tmp_path / "installed"


def _write_step(tmp_path, step_id="write"):
    # A subprocess-free step (write a marker file) so the test does not depend
    # on a shell/interpreter being on PATH in the test environment.
    return {
        "type": "write-file",
        "id": step_id,
        "path": str(_installed_marker(tmp_path)),
        "content": "done",
    }


def test_declared_step_install_runs_steps(tmp_path):
    from audiagentic.foundation.toolchains.recipe_patterns import (
        DeclaredStepRecipe,
        InstallManifest,
    )

    r = DeclaredStepRecipe(
        InstallManifest(install_steps=(_write_step(tmp_path),), verified=True), {}
    )
    result = r.install({})
    assert result.success and result.state is RecipeState.INSTALLING
    assert _installed_marker(tmp_path).exists()


def test_declared_step_gate_blocks_unverified_source():
    from audiagentic.foundation.toolchains.recipe_patterns import (
        DeclaredStepRecipe,
        InstallManifest,
    )

    r = DeclaredStepRecipe(
        InstallManifest(
            install_steps=({"type": "shell", "id": "x", "command": ["echo", "hi"]},),
            verified=False,
            source_label="unconfirmed",
            gate_action="verify the source first",
        ),
        {},
        subject="installer",
    )
    inst = r.install({})
    assert not inst.success
    assert inst.error == "installer source unconfirmed; refusing to execute"
    assert inst.action_needed == "verify the source first"

    probed = r.probe({})
    assert probed.state is RecipeState.ABSENT
    assert probed.status == "source unconfirmed; installer blocked"


def test_declared_step_no_steps_fails():
    from audiagentic.foundation.toolchains.recipe_patterns import (
        DeclaredStepRecipe,
        InstallManifest,
    )

    r = DeclaredStepRecipe(InstallManifest(verified=True), {})
    assert not r.install({}).success
    assert r.install({}).error == "no install steps for this installer"


def test_declared_step_verify_without_probe_is_verified():
    from audiagentic.foundation.toolchains.recipe_patterns import (
        DeclaredStepRecipe,
        InstallManifest,
    )

    r = DeclaredStepRecipe(InstallManifest(verified=True), {})
    v = r.verify({})
    assert v.success and v.state is RecipeState.VERIFIED
    assert v.status == "installer completed; no status probe available"


def test_declared_step_subject_customizes_messages():
    from audiagentic.foundation.toolchains.recipe_patterns import (
        DeclaredStepRecipe,
        InstallManifest,
    )

    r = DeclaredStepRecipe(
        InstallManifest(verified=False, source_label="blocked"), {}, subject="plugin installer"
    )
    assert r.probe({}).status == "source blocked; plugin installer blocked"


# ---- Boundary guard: no component imports in the pattern module ------------

def test_recipe_patterns_has_no_component_imports():
    import audiagentic.foundation.toolchains.recipe_patterns as patterns

    source = Path(patterns.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "audiagentic.components" not in stripped, f"component import: {stripped}"
    # domain-neutral vocabulary (Std §1): no capability-specific terms
    for term in ("hindsight", "audia_action", "HindsightBackend"):
        assert term not in source, f"domain term {term!r} leaked into foundation pattern"
