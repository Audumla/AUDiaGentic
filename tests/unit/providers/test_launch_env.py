"""MO15 launch-env contribution seam tests."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from audiagentic.components.providers.services import launch_env
from audiagentic.components.providers.services.recipes import (
    LaunchEnvContributionRecipe,
    ProviderRecipeKind,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

_SENTINEL = "sekrit-canary-value-9812"


@pytest.fixture(autouse=True)
def _clean_registry():
    launch_env._contributions.clear()
    yield
    launch_env._contributions.clear()


def test_contribution_listing_shows_names_and_schemes_only(monkeypatch) -> None:
    launch_env.register_launch_env_contribution(
        "prov-x", {"API_KEY": "env:SOME_UPSTREAM_KEY", "MODEL_PREFIX": "openai/"}
    )
    summary = launch_env.list_launch_env_contributions("prov-x")
    assert summary == {"API_KEY": "env", "MODEL_PREFIX": "literal"}
    # No value, no locator content beyond what was registered as a ref.
    assert _SENTINEL not in str(summary)


def test_overlay_injects_into_environ_and_restores(monkeypatch) -> None:
    monkeypatch.setenv("SOME_UPSTREAM_KEY", _SENTINEL)
    monkeypatch.delenv("INJECTED_TARGET", raising=False)
    launch_env.register_launch_env_contribution(
        "prov-x", {"INJECTED_TARGET": "env:SOME_UPSTREAM_KEY"}
    )

    with launch_env.launch_env_overlay("prov-x") as injected:
        assert os.environ["INJECTED_TARGET"] == _SENTINEL
        # The yield surface reports names only, never values.
        assert injected == {"INJECTED_TARGET": "injected"}

    assert "INJECTED_TARGET" not in os.environ


def test_overlay_restores_pre_existing_value(monkeypatch) -> None:
    monkeypatch.setenv("SOME_UPSTREAM_KEY", _SENTINEL)
    monkeypatch.setenv("INJECTED_TARGET", "user-original")
    launch_env.register_launch_env_contribution(
        "prov-x", {"INJECTED_TARGET": "env:SOME_UPSTREAM_KEY"}
    )
    with launch_env.launch_env_overlay("prov-x"):
        assert os.environ["INJECTED_TARGET"] == _SENTINEL
    assert os.environ["INJECTED_TARGET"] == "user-original"


def test_overlay_missing_env_var_raises_canonical_error_with_name_only(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_UPSTREAM_KEY", raising=False)
    launch_env.register_launch_env_contribution(
        "prov-x", {"TARGET": "env:MISSING_UPSTREAM_KEY"}
    )
    with pytest.raises(AudiaGenticError) as exc:
        with launch_env.launch_env_overlay("prov-x"):
            pass
    assert exc.value.code == "CON-SEC-001"
    assert _SENTINEL not in str(exc.value)


def test_execute_provider_applies_overlay(monkeypatch) -> None:
    """The dispatch seam wraps the runner so subprocesses inherit the env."""
    from audiagentic.components.providers.services import execution

    monkeypatch.setenv("SOME_UPSTREAM_KEY", _SENTINEL)
    launch_env.register_launch_env_contribution(
        "fake-prov", {"INJECTED_TARGET": "env:SOME_UPSTREAM_KEY"}
    )

    seen: dict = {}

    def fake_runner(packet_ctx, provider_cfg):
        seen["value"] = os.environ.get("INJECTED_TARGET")
        return {"status": "ok", "output": "done"}

    monkeypatch.setattr(execution, "_load_runner", lambda pid: fake_runner)
    result = execution.execute_provider(
        provider_id="fake-prov", packet_ctx={}, provider_cfg={}
    )
    assert seen["value"] == _SENTINEL
    assert "INJECTED_TARGET" not in os.environ
    # Redaction canary: the resolved value never appears in the result surface.
    assert _SENTINEL not in str(result)


def test_recipe_inert_for_stub_execution_provider() -> None:
    """openhands has execution: stub — contribution must stay inert (MO04 v7)."""
    recipe = LaunchEnvContributionRecipe(
        "openhands", "model-source-env", {"LLM_API_KEY": "env:SOME_UPSTREAM_KEY"}
    )
    assert recipe.recipe_kind is ProviderRecipeKind.LAUNCH_ENV

    result = recipe.configure({})
    assert result.success
    assert "inert" in result.status
    assert "execution bridge not wired" in result.action_needed
    assert launch_env.list_launch_env_contributions("openhands") == {}

    probe = recipe.probe({})
    assert probe.state.name == "ABSENT"
    assert "execution bridge not wired" in probe.action_needed


def test_recipe_registers_for_real_execution_provider(monkeypatch) -> None:
    monkeypatch.setenv("SOME_UPSTREAM_KEY", _SENTINEL)
    recipe = LaunchEnvContributionRecipe(
        "qwen", "model-source-env", {"UPSTREAM_KEY": "env:SOME_UPSTREAM_KEY"}
    )
    result = recipe.configure({})
    assert result.success
    assert result.state.name == "VERIFIED"
    assert launch_env.list_launch_env_contributions("qwen") == {"UPSTREAM_KEY": "env"}
    # Status surfaces carry names/schemes only.
    assert _SENTINEL not in str(result)

    pruned = recipe.prune({})
    assert pruned.success
    assert launch_env.list_launch_env_contributions("qwen") == {}


def test_recipe_reports_standalone_gap_when_ambient_var_missing(monkeypatch) -> None:
    """RV338: launch-env-only pairs report 'AG-launched sessions only'."""
    monkeypatch.delenv("MISSING_UPSTREAM_KEY", raising=False)
    recipe = LaunchEnvContributionRecipe(
        "qwen", "model-source-env", {"UPSTREAM_KEY": "env:MISSING_UPSTREAM_KEY"}
    )
    probe = recipe.probe({})
    assert probe.state.name == "ABSENT"
    assert "works in AG-launched sessions only" in probe.status
    assert "MISSING_UPSTREAM_KEY" in probe.action_needed
    assert "shell environment" in probe.action_needed


def test_foundation_secrets_has_no_component_imports() -> None:
    """Architecture guard (MO15 step 6): foundation/secrets.py imports no
    component/runtime modules; prompt templating has no secrets dependency."""
    root = Path(__file__).resolve().parents[3] / "src" / "audiagentic"

    secrets_tree = ast.parse((root / "foundation" / "secrets.py").read_text(encoding="utf-8"))
    for node in ast.walk(secrets_tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            assert not name.startswith("audiagentic.components"), name
            assert not name.startswith("audiagentic.runtime"), name

    templates_src = (root / "foundation" / "templates.py").read_text(encoding="utf-8")
    assert "secrets" not in templates_src
