from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.registry_utils import Registry, reset_all_registries


def test_registry_loader_runs_once_and_again_after_reset() -> None:
    calls = 0

    def _load() -> None:
        nonlocal calls
        calls += 1
        registry.register("one", object())

    registry: Registry[object] = Registry(loader=_load)

    assert registry.keys() == ("one",)
    assert registry.all().keys() == {"one"}
    assert registry.get("one") is not None
    assert calls == 1

    registry.reset()

    assert registry.get("one") is not None
    assert calls == 2


def test_registry_loader_does_not_recurse() -> None:
    calls = 0

    def _load() -> None:
        nonlocal calls
        calls += 1
        assert registry.get("missing") is None
        registry.register("one", object())

    registry: Registry[object] = Registry(loader=_load)

    assert registry.get("one") is not None
    assert calls == 1


def test_registry_collision_errors_are_catalogued() -> None:
    first = object()
    registry: Registry[object] = Registry(aliases=True)
    registry.register("one", first, aliases=["uno"])

    with pytest.raises(AudiaGenticError) as key_conflict:
        registry.register("one", object())
    assert key_conflict.value.code == "VAL-REG-001"

    with pytest.raises(AudiaGenticError) as alias_conflict:
        registry.register("two", object(), aliases=["uno"])
    assert alias_conflict.value.code == "VAL-REG-002"

    with pytest.raises(AudiaGenticError) as alias_shadow:
        registry.register("three", object(), aliases=["one"])
    assert alias_shadow.value.code == "VAL-REG-003"


def test_reset_all_registries_clears_loader_state() -> None:
    calls = 0

    def _load() -> None:
        nonlocal calls
        calls += 1
        registry.register("one", object())

    registry: Registry[object] = Registry(loader=_load)
    assert registry.get("one") is not None
    reset_all_registries()
    assert registry.get("one") is not None
    assert calls == 2
