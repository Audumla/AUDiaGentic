"""HA04: OpenCode interactive launch is now a declarative recipe (no builder).

Exercises the recipe path end to end: resolve_launch_builder finds the
descriptor's interactive: block (not a hand-written module) and builds a
ProviderLaunch via build_launch_spec; runner args translate from the recipe's
runner-flags.
"""
from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.recipe_launch import (
    translate_recipe_runner_args,
)
from audiagentic.components.providers.services.execution.execution import resolve_launch_builder
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError

register_all_components()


@dataclass
class _RunnerParams:
    prompt: str | None = None
    mode: str | None = None
    verbose: bool = False


@pytest.fixture(autouse=True)
def _which(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.cli.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )


def _build(**kw):
    builder = resolve_launch_builder("opencode", "interactive")
    assert builder is not None
    assert builder.__module__ == "audiagentic.components.providers.adapters.recipe_launch"
    defaults = dict(provider="audiagentic", model="m", agent_runtime=Path("/rt"))
    defaults.update(kw)
    return builder(Path("/proj"), **defaults)


def test_resolved_via_recipe_not_hand_written() -> None:
    # There is no adapters/opencode/interactive.py anymore.
    builder = resolve_launch_builder("opencode", "interactive")
    assert builder.__module__ == "audiagentic.components.providers.adapters.recipe_launch"


def test_basic_launch_shape() -> None:
    launch = _build()
    assert launch.executable == "/usr/bin/opencode"
    assert launch.args == ()
    assert dict(launch.environment) == {}


def test_mcp_surface_env_merged() -> None:
    surface = types.SimpleNamespace(extra_args=(), extra_env={"OPENCODE_CONFIG_CONTENT": "{}"})
    launch = _build(mcp_surface=surface)
    assert launch.environment["OPENCODE_CONFIG_CONTENT"] == "{}"


def test_missing_cli_raises_uniform_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.cli.shutil.which", lambda name: None
    )
    with pytest.raises(AudiaGenticError) as exc:
        _build()
    assert exc.value.code == "EXT-PROVCLI-001"


def test_runner_flags_translate_from_recipe() -> None:
    assert translate_recipe_runner_args("opencode", _RunnerParams(prompt="hi", mode="json")) == [
        "--output-format", "json", "--message", "hi",
    ]
    assert translate_recipe_runner_args("opencode", _RunnerParams(mode="text")) == []
    assert translate_recipe_runner_args("opencode", None) == []
