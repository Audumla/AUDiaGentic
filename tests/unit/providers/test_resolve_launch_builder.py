"""HA04: open-ended, name-based launch dispatch.

The caller picks a launch profile *by name* (not a closed enum); the
provider's builder owns which transports/channels it assembles. The
descriptor's declared ``launches`` (name -> channel surface by role) is the
source of truth for whether a profile is supported -- an unrecognized name is
simply unsupported, never an error.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.execution.execution import resolve_launch_builder
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError

register_all_components()


def test_interactive_hand_written_hook_wins() -> None:
    builder = resolve_launch_builder("pi", "interactive")
    assert builder is not None
    assert builder.__module__ == "audiagentic.components.providers.adapters.pi.interactive"


def test_agent_intent_uses_acp_builder() -> None:
    builder = resolve_launch_builder("opencode", "agent")
    assert builder is not None
    assert builder.__module__ == "audiagentic.components.providers.adapters.opencode.acp"


def test_interactive_recipe_when_no_hook() -> None:
    # opencode has no interactive.py -> resolves the declarative recipe
    builder = resolve_launch_builder("opencode", "interactive")
    assert builder.__module__ == "audiagentic.components.providers.adapters.recipe_launch"


def test_execute_resolves_a_runner() -> None:
    assert resolve_launch_builder("qwen", "execute") is not None


def test_unrecognized_profile_name_is_unsupported_not_an_error() -> None:
    # "telepathy" isn't in pi's declared launches -- unsupported, no exception.
    assert resolve_launch_builder("pi", "telepathy") is None


def test_undeclared_intent_is_unsupported(monkeypatch) -> None:
    from audiagentic.components.providers.services.execution import execution as exec_mod

    monkeypatch.setattr(
        exec_mod, "_declared_launches",
        lambda pid: {"execute": {}, "interactive": {}},  # no 'agent'
    )
    assert resolve_launch_builder("pi", "agent") is None


def test_declared_intent_without_builder_fails_closed(monkeypatch) -> None:
    from audiagentic.components.providers.services.execution import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {"agent": {}})
    monkeypatch.setattr(exec_mod, "_adapter_hook", lambda pid, sub, fn: None)
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.recipe_launch.descriptor_launch_builder",
        lambda pid, block: None,
    )
    with pytest.raises(AudiaGenticError) as exc:
        resolve_launch_builder("pi", "agent")
    assert exc.value.code == "INT-EXEC-003"


def test_undeclared_launches_falls_back_to_probing(monkeypatch) -> None:
    from audiagentic.components.providers.services.execution import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {})
    assert resolve_launch_builder("pi", "interactive") is not None


def test_new_profile_name_uses_convention_no_registry_edit_needed(monkeypatch) -> None:
    """A launch profile with no _LAUNCH_BUILDERS entry is looked up by
    convention -- adapters/<id>/<name>.py::build_launch -- no dict edit."""
    from audiagentic.components.providers.services.execution import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {"benchmark": {}})
    calls: list[tuple[str, str, str]] = []

    def _fake_hook(pid, sub, fn):
        calls.append((pid, sub, fn))
        return lambda: "builder"

    monkeypatch.setattr(exec_mod, "_adapter_hook", _fake_hook)
    builder = resolve_launch_builder("pi", "benchmark")
    assert builder is not None
    assert calls == [("pi", "benchmark", "build_launch")]


def test_pi_opencode_declare_the_three_intents_with_channel_surfaces() -> None:
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    d = all_descriptors()
    for pid in ("pi", "opencode"):
        launches = d[pid].launches
        assert set(launches) == {"execute", "interactive", "agent"}
        # agent intent is driven over acp
        assert "acp" in launches["agent"]["interaction"]
    # pi additionally advertises rpc observability for the agent intent
    assert "rpc" in d["pi"].launches["agent"]["observability"]
