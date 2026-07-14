from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.managed_config import (
    ManagedConfigSpec,
    ManagedFragmentRegistry,
    resolve_managed_config_path,
)


def _spec(path):
    return ManagedConfigSpec(
        config_path=path,
        reader=lambda _: {},
        writer=lambda _path, _entries: None,
        remover=lambda _path, _name: False,
    )


def test_resolve_managed_config_path_supports_relative_absolute_and_callable(tmp_path: Path) -> None:
    assert resolve_managed_config_path(_spec(".tool/config.json"), tmp_path) == tmp_path / ".tool/config.json"
    assert resolve_managed_config_path(_spec(tmp_path / "absolute.json"), tmp_path) == tmp_path / "absolute.json"
    assert resolve_managed_config_path(_spec(lambda root: root / "callable.json"), tmp_path) == tmp_path / "callable.json"


def test_resolve_managed_config_path_rejects_invalid_callable_result(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        resolve_managed_config_path(_spec(lambda _root: None), tmp_path)
    assert raised.value.code == "VAL-MCFG-001"


def test_registry_missing_roundtrip_and_corruption(tmp_path: Path) -> None:
    registry = ManagedFragmentRegistry(tmp_path, "managed-fixture.json", top_level_key="providers")
    assert registry.load() == {}

    registry.save({"fixture": {"owned/id": "visible-name"}})
    assert registry.load() == {"fixture": {"owned/id": "visible-name"}}

    registry.path.write_text("{bad json", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as raised:
        registry.load()
    assert raised.value.code == "CON-MCFG-001"


def test_registry_rejects_wrong_contract_root(tmp_path: Path) -> None:
    registry = ManagedFragmentRegistry(tmp_path, "managed-fixture.json")
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({"contract-version": "v1", "wrong": {}}), encoding="utf-8")

    with pytest.raises(AudiaGenticError) as raised:
        registry.load()
    assert raised.value.code == "CON-MCFG-001"
