"""The gateway knows which provider surfaces it can dispatch to and refuses the rest up front."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway import health as health_module
from audiagentic.components.agents.gateway.health import DispatchHealth
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_a_missing_provider_module_marks_its_surface_unavailable_with_the_cause() -> None:
    registry = DispatchHealth(finder=lambda name: None if name == "websockets" else object())
    registry.refresh_dependencies()
    snapshot = registry.snapshot()
    assert snapshot["ready"] is False and snapshot["degraded"] == ["gpt-auto-cdp"]
    surface = snapshot["surfaces"]["gpt-auto-cdp"]
    assert surface["reason_code"] == "dependency-missing" and "websockets" in surface["detail"]
    with pytest.raises(AudiaGenticError) as raised:
        registry.require_available("gpt-auto-cdp")
    assert raised.value.code == "RES-AGW-154" and "runtime install" in raised.value.message


def test_present_modules_and_unprobed_surfaces_are_admitted() -> None:
    registry = DispatchHealth(finder=lambda name: object())
    registry.refresh_dependencies()
    assert registry.snapshot()["ready"] is True
    registry.require_available("gpt-auto-cdp")
    registry.require_available("some-surface-nobody-probed")  # silence is never a refusal


def test_recovery_after_the_module_appears_and_unchanged_state_keeps_its_timestamp() -> None:
    present = {"websockets": False}
    registry = DispatchHealth(finder=lambda name: object() if present[name] else None)
    registry.refresh_dependencies()
    first = registry.snapshot()["surfaces"]["gpt-auto-cdp"]["since"]
    registry.refresh_dependencies()
    assert registry.snapshot()["surfaces"]["gpt-auto-cdp"]["since"] == first
    present["websockets"] = True
    registry.refresh_dependencies()
    assert registry.snapshot()["ready"] is True


def test_profile_resolution_refuses_an_unavailable_surface(monkeypatch) -> None:
    registry = DispatchHealth(finder=lambda name: None)
    registry.refresh_dependencies()
    monkeypatch.setattr(health_module, "_HEALTH", registry)
    from audiagentic.components.agents.gateway import profiles

    class Surface:
        class ref:  # noqa: N801
            surface_id = "gpt-auto-cdp"
            resolved_version = "1"

        class validation:  # noqa: N801
            class evidence:  # noqa: N801
                validated = True

    monkeypatch.setattr("audiagentic.components.agents.configuration.global_catalog.resolve_global_execution_profile",
                        lambda _root, _id: {"profile_id": "p", "provider_id": "gpt-auto", "instances": ["x"],
                                            "surface_id": "gpt-auto-cdp"})
    from pathlib import Path

    with pytest.raises(AudiaGenticError) as raised:
        profiles.resolve_for_admission(Path("."), "p", surface_resolver=lambda *_a: Surface,
                                       allow_test_fallback=True)
    assert raised.value.code == "RES-AGW-154"
