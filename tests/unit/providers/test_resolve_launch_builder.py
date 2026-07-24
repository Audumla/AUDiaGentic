"""HA04: mode x transport launch dispatch.

Modes: execute (run a turn, capture) | interactive (live session).
Transports: native (pipe/tty) | acp (Agent Client Protocol, provider-gated).
Capability (descriptor.launches: mode -> transport set) is the source of truth.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.execution import resolve_launch_builder
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError

register_all_components()


def test_interactive_native_hand_written_hook_wins() -> None:
    builder = resolve_launch_builder("pi", "interactive", "native")
    assert builder is not None
    assert builder.__module__ == "audiagentic.components.providers.adapters.pi.interactive"


def test_interactive_acp_transport_builder() -> None:
    builder = resolve_launch_builder("opencode", "interactive", "acp")
    assert builder is not None
    assert builder.__module__ == "audiagentic.components.providers.adapters.opencode.acp"


def test_interactive_native_recipe_when_no_hook() -> None:
    # opencode has no interactive.py -> resolves the declarative recipe
    builder = resolve_launch_builder("opencode", "interactive", "native")
    assert builder.__module__ == "audiagentic.components.providers.adapters.recipe_launch"


def test_execute_native_resolves_a_runner() -> None:
    assert resolve_launch_builder("qwen", "execute", "native") is not None


def test_unknown_pair_raises() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        resolve_launch_builder("pi", "interactive", "carrier-pigeon")
    assert exc.value.code == "VAL-EXEC-004"


def test_undeclared_transport_is_unsupported(monkeypatch) -> None:
    """A transport absent from the provider's declared set for a mode -> None."""
    from audiagentic.components.providers.services import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {"interactive": ("native",)})
    # acp not declared for interactive -> unsupported even if acp.py exists
    assert resolve_launch_builder("pi", "interactive", "acp") is None


def test_declared_pair_without_builder_fails_closed(monkeypatch) -> None:
    from audiagentic.components.providers.services import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {"interactive": ("acp",)})
    monkeypatch.setattr(exec_mod, "_adapter_hook", lambda pid, sub, fn: None)
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.recipe_launch.descriptor_launch_builder",
        lambda pid, block: None,
    )
    with pytest.raises(AudiaGenticError) as exc:
        resolve_launch_builder("pi", "interactive", "acp")
    assert exc.value.code == "INT-EXEC-003"


def test_undeclared_launches_falls_back_to_probing(monkeypatch) -> None:
    from audiagentic.components.providers.services import execution as exec_mod

    monkeypatch.setattr(exec_mod, "_declared_launches", lambda pid: {})
    assert resolve_launch_builder("pi", "interactive", "native") is not None


def test_pi_and_opencode_declare_the_expected_launches() -> None:
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    d = all_descriptors()
    assert dict(d["pi"].launches) == {"execute": ["native"], "interactive": ["native", "acp"]}
    assert dict(d["opencode"].launches) == {"execute": ["native"], "interactive": ["native", "acp"]}
