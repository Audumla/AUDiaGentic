"""MO02 model-endpoint sync tests: ownership, collisions, truth-table, boundaries."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.descriptors import registry as descriptor_registry
from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.services.models import (
    MaterializedModelEntry,
    materialize_local_endpoint_sources,
    model_ownership_registry,
    sync_managed_provider_models,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.managed_config import ManagedConfigSpec

# --- fake provider: flat JSON file of {name: payload} -----------------------


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, entries: dict) -> None:
    current = _read_json(path)
    current.update(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def _remove_json(path: Path, name: str) -> bool:
    current = _read_json(path)
    if name not in current:
        return False
    del current[name]
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return True


def _render(entry: MaterializedModelEntry) -> tuple[str, dict]:
    return entry.visible_name, {
        "model": entry.model_id,
        "baseUrl": entry.endpoint.get("base-url"),
        "limits": entry.limits,
    }


def _fake_descriptor(**overrides) -> ProviderDescriptor:
    fields = dict(
        provider_id="fakemodels",
        display_name="Fake Models Provider",
        model_config=ManagedConfigSpec(
            config_path=".fake/models.json",
            reader=_read_json,
            writer=_write_json,
            remover=_remove_json,
            format="fake-json",
            refresh_mode="file-watch",
        ),
        supported_connectors=("openai-compatible",),
        model_entry_renderer=_render,
    )
    fields.update(overrides)
    return ProviderDescriptor(**fields)


@pytest.fixture
def fake_provider(monkeypatch):
    descriptor = _fake_descriptor()
    original = descriptor_registry.get_descriptor
    monkeypatch.setattr(
        descriptor_registry,
        "get_descriptor",
        lambda pid: descriptor if pid == "fakemodels" else original(pid),
    )
    return descriptor


def _entry(source_id: str, model_id: str, connector: str = "openai-compatible") -> MaterializedModelEntry:
    return MaterializedModelEntry(
        source_id=source_id,
        model_id=model_id,
        visible_name=source_id,
        connector=connector,
        managed_id=f"model-endpoints/{source_id}",
        endpoint={"base-url": "http://127.0.0.1:1234/v1"},
        limits={"context-window": 8192},
    )


# --- ownership roundtrip ------------------------------------------------------


def test_apply_update_remove_preserves_unmanaged(fake_provider, tmp_path: Path) -> None:
    config_path = tmp_path / ".fake" / "models.json"
    _write_json(config_path, {"user-model": {"model": "users-own"}})

    result = sync_managed_provider_models(
        "fakemodels", tmp_path, [_entry("local-a", "model-a"), _entry("local-b", "model-b")]
    )
    assert result["ok"] is True
    assert sorted(result["updated"]) == ["local-a", "local-b"]
    data = _read_json(config_path)
    assert data["user-model"] == {"model": "users-own"}
    assert data["local-a"]["model"] == "model-a"

    # update one, remove the other
    result = sync_managed_provider_models(
        "fakemodels", tmp_path, [_entry("local-a", "model-a-v2")]
    )
    assert result["ok"] is True
    data = _read_json(config_path)
    assert data["local-a"]["model"] == "model-a-v2"
    assert "local-b" not in data
    assert data["user-model"] == {"model": "users-own"}

    owned = model_ownership_registry(tmp_path).load()["fakemodels"]
    assert owned == {"model-endpoints/local-a": "local-a"}


def test_empty_desired_prunes_owned_only(fake_provider, tmp_path: Path) -> None:
    config_path = tmp_path / ".fake" / "models.json"
    _write_json(config_path, {"user-model": {"model": "users-own"}})
    sync_managed_provider_models("fakemodels", tmp_path, [_entry("local-a", "model-a")])

    result = sync_managed_provider_models("fakemodels", tmp_path, [])
    assert result["ok"] is True
    assert result["removed"] == ["local-a"]
    data = _read_json(config_path)
    assert data == {"user-model": {"model": "users-own"}}
    assert model_ownership_registry(tmp_path).load().get("fakemodels", {}) == {}


def test_cross_managed_id_name_collision_reported(fake_provider, tmp_path: Path) -> None:
    sync_managed_provider_models("fakemodels", tmp_path, [_entry("shared-name", "model-a")])
    colliding = MaterializedModelEntry(
        source_id="other-source",
        model_id="model-b",
        visible_name="shared-name",  # same provider-visible name, different managed id
        connector="openai-compatible",
        managed_id="model-endpoints/other-source",
    )
    result = sync_managed_provider_models(
        "fakemodels", tmp_path, [_entry("shared-name", "model-a"), colliding]
    )
    assert result["ok"] is False
    assert result["collisions"]


def test_unsupported_connector_is_skipped_not_projected(fake_provider, tmp_path: Path) -> None:
    result = sync_managed_provider_models(
        "fakemodels", tmp_path, [_entry("anthropic-src", "claude-x", connector="anthropic")]
    )
    assert result["ok"] is True
    assert result["updated"] == []
    assert result["skipped_connectors"][0]["connector"] == "anthropic"
    assert not (tmp_path / ".fake" / "models.json").exists()


def test_provider_without_model_config_is_clean_skip(tmp_path: Path) -> None:
    result = sync_managed_provider_models("claude", tmp_path, [])
    assert result == {"provider_id": "claude", "ok": True, "skipped": "no model_config defined"}


def test_model_config_without_renderer_raises(monkeypatch, tmp_path: Path) -> None:
    descriptor = _fake_descriptor(model_entry_renderer=None)
    monkeypatch.setattr(descriptor_registry, "get_descriptor", lambda pid: descriptor)
    with pytest.raises(AudiaGenticError) as exc:
        sync_managed_provider_models("fakemodels", tmp_path, [_entry("a", "m")])
    assert exc.value.code == "VAL-MEP-002"


# --- materialization ----------------------------------------------------------


def test_materialize_local_endpoint_sources_maps_fields() -> None:
    document = {
        "contract-version": "v1",
        "sources": {
            "local-a": {
                "source-class": "local-endpoint",
                "connector": "openai-compatible",
                "base-url": "http://127.0.0.1:1234/v1",
                "api-key-ref": "env:LOCAL_KEY",
                "model-id": "model-a",
                "display-name": "Local A",
                "context-window": 131072,
                "capabilities": {"tool-use": True},
            },
            "disabled-b": {
                "source-class": "local-endpoint",
                "connector": "openai-compatible",
                "model-id": "model-b",
                "enabled": False,
            },
            "remote-c": {
                "source-class": "remote-account",
                "connector": "openrouter",
                "api-key-ref": "env:OR_KEY",
            },
        },
    }
    entries = materialize_local_endpoint_sources(document)
    assert [entry.source_id for entry in entries] == ["local-a"]
    entry = entries[0]
    assert entry.managed_id == "model-endpoints/local-a"
    assert entry.model_id == "model-a"
    assert entry.visible_name == "Local A"
    assert entry.endpoint["base-url"] == "http://127.0.0.1:1234/v1"
    assert entry.limits["context-window"] == 131072
    assert entry.auth_ref == "env:LOCAL_KEY"


# --- mutation truth table (MO02 step 11) --------------------------------------

_SOURCE = {
    "source-class": "local-endpoint",
    "connector": "openai-compatible",
    "base-url": "http://127.0.0.1:1234/v1",
    "model-id": "model-a",
}


def _sources_file(tmp_path: Path) -> Path:
    return tmp_path / ".audiagentic" / "config" / "model-sources.yaml"


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = providers_api.model_source_add(
        tmp_path, "local-a", dict(_SOURCE), apply=True, dry_run=True
    )
    assert result["dry_run"] is True
    assert result["applied"] is False
    assert result["diff"]["added"] == ["local-a"]
    assert not _sources_file(tmp_path).exists()
    assert not model_ownership_registry(tmp_path).path.exists()


def test_write_without_apply_commits_desired_only(tmp_path: Path) -> None:
    result = providers_api.model_source_add(
        tmp_path, "local-a", dict(_SOURCE), apply=False, dry_run=False
    )
    assert result["written"] is True
    assert result["applied"] is False
    assert _sources_file(tmp_path).exists()


def test_apply_writes_then_reconciles(tmp_path: Path) -> None:
    result = providers_api.model_source_add(
        tmp_path, "local-a", dict(_SOURCE), apply=True, dry_run=False
    )
    assert result["written"] is True
    # no shipped provider declares model_config yet, so the sync trivially succeeds
    assert result["applied"] is True
    assert result["sync"]["ok"] is True


def test_add_duplicate_rejected(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE), apply=False)
    with pytest.raises(AudiaGenticError):
        providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE), apply=False)


def test_update_remove_set_enabled_roundtrip(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE), apply=False)

    providers_api.model_source_set_enabled(tmp_path, "local-a", False, apply=False)
    listing = providers_api.model_source_list(tmp_path)
    assert listing["sources"]["local-a"]["enabled"] is False

    providers_api.model_source_update(
        tmp_path, "local-a", {"display-name": "Renamed"}, apply=False
    )
    providers_api.model_source_remove(tmp_path, "local-a", apply=False)
    assert providers_api.model_source_list(tmp_path)["sources"] == {}


def test_update_unknown_source_rejected(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError):
        providers_api.model_source_update(tmp_path, "nope", {"enabled": False}, apply=False)


def test_invalid_config_rejected_without_partial_write(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.model_source_add(
            tmp_path, "bad", {"source-class": "nope", "connector": "openai-compatible"}, apply=False
        )
    assert exc.value.code == "VAL-MEP-001"
    assert not _sources_file(tmp_path).exists()


# --- status fields (MO02 step 7) -----------------------------------------------


def test_model_config_status_fields(fake_provider, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.status import _model_config_status

    sync_managed_provider_models(
        "fakemodels", tmp_path, [_entry("local-a", "model-a")]
    )
    status = _model_config_status("fakemodels", fake_provider, tmp_path)
    assert status["supported"] is True
    assert status["format"] == "fake-json"
    assert status["refresh-mode"] == "file-watch"
    assert status["managed-model-count"] == 1
    assert status["managed-ids"] == ["model-endpoints/local-a"]
    assert status["config-path"].endswith("models.json")


def test_model_config_status_unsupported_provider(tmp_path: Path) -> None:
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.status import _model_config_status

    status = _model_config_status("claude", get_descriptor("claude"), tmp_path)
    assert status["supported"] is False
    assert status["managed-model-count"] == 0


# --- renderer boundary (MO02 validation 9) ------------------------------------


def test_models_service_has_no_adapter_imports_or_provider_branches() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "src" / "audiagentic" / "components" / "providers" / "services" / "models.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            assert ".adapters" not in name, f"models.py must not import adapters: {name}"
    # No provider-id equality branches (registry/descriptor data drives dispatch).
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            text = ast.unparse(node)
            assert "provider_id ==" not in text, text
