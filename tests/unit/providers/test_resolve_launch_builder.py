"""HA04: intent-based launch dispatch.

The caller picks an INTENT (execute | interactive | agent); the provider's
builder owns which transports/channels it assembles. The descriptor's declared
``launches`` (intent -> channel surface by role) is the source of truth for
whether an intent is supported.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.execution import resolve_launch_builder
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


def test_unknown_intent_raises() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        resolve_launch_builder("pi", "telepathy")
    assert exc.value.code == "VAL-EXEC-004"


def test_undeclared_intent_is_unsupported(monkeypatch) -> None:
    from audiagentic.components.providers.services import execution as exec_mod

    monkeypatch.setattr(
        exec_mod, "_declared_launches",
        lambda pid: {"execute": {}, "interactive": {}},  # no 'agent'
    )
    assert resolve_launch_builder("pi", "agent") is None


def test_declared_intent_without_builder_fails_closed(monkeypatch) -> None:
    from audiagentic.components.providers.services import execution as exec_mod

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
    from audiagentic.components.providers.services import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {})
    assert resolve_launch_builder("pi", "interactive") is not None


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
