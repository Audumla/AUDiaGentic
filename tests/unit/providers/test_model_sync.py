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
    build_model_projection_request,
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


def test_resource_crud_commits_desired_only(tmp_path: Path) -> None:
    result = providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE))
    assert result["written"] is True
    assert result["diff"]["added"] == ["local-a"]
    assert _sources_file(tmp_path).exists()
    assert not model_ownership_registry(tmp_path).path.exists()


def test_resource_crud_has_no_automation_flags() -> None:
    import inspect

    for operation in (
        providers_api.model_source_add,
        providers_api.model_source_update,
        providers_api.model_source_remove,
        providers_api.model_source_set_enabled,
    ):
        parameters = inspect.signature(operation).parameters
        assert "apply" not in parameters
        assert "dry_run" not in parameters


def test_public_model_projection_plan_uses_registered_family(tmp_path: Path) -> None:
    request = providers_api.ModelProjectionRequest(
        managed_ids=("model-endpoints/local-a",),
        entries=(
            providers_api.ModelProjectionEntry(
                source_id="local-a",
                model_id="model-a",
                visible_name="Local A",
                connector="openai",
                managed_id="model-endpoints/local-a",
                endpoint={"base-url": "http://127.0.0.1:1234/v1"},
            ),
        ),
    )

    result = providers_api.manage_model_projection(
        tmp_path, "pi", mode="plan", request=request
    )

    assert isinstance(result, providers_api.ModelProjectionResult)
    assert result.ok is True
    assert result.supported is True
    assert result.provider_id == "pi"
    assert result.added == ("model-endpoints/local-a",)
    assert not (tmp_path / ".pi" / "agent" / "models.json").exists()


def test_projection_request_includes_stale_owned_ids(fake_provider, tmp_path: Path) -> None:
    model_ownership_registry(tmp_path).save(
        {"fakemodels": {"model-endpoints/removed": "Removed"}}
    )
    providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE))

    request = build_model_projection_request(
        tmp_path, "fakemodels", enabled=True
    )

    assert request.managed_ids == (
        "model-endpoints/local-a",
        "model-endpoints/removed",
    )
    assert tuple(entry.managed_id for entry in request.entries) == (
        "model-endpoints/local-a",
    )


def test_cached_vendor_catalog_materializes_filtered_models(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "anthropic-endpoint", {
        "source-class": "remote-account",
        "connector": "anthropic",
        "model-discovery": "list-api",
        "model-filter": {"include": ["claude-*"]},
        "api-key-ref": "env:ANTHROPIC_API_KEY",
    })
    cache = (
        tmp_path / ".audiagentic" / "runtime" / "providers"
        / "source-catalogs" / "anthropic-endpoint.json"
    )
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({
        "contract-version": "v1",
        "source-id": "anthropic-endpoint",
        "discovery-mode": "list-api",
        "fetched-at": "2026-07-18T00:00:00Z",
        "models": [
            {"model-id": "claude-sonnet", "context-window": 200000},
            {"model-id": "other-model"},
        ],
    }), encoding="utf-8")

    request = build_model_projection_request(tmp_path, "pi", enabled=True)

    assert request.managed_ids == (
        "model-endpoints/anthropic-endpoint/claude-sonnet",
    )
    assert request.entries[0].connector == "anthropic"
    assert request.entries[0].auth_ref == "env:ANTHROPIC_API_KEY"


def test_native_vendor_group_is_not_duplicated_as_custom_entries(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "anthropic-main", {
        "source-class": "remote-account",
        "vendor-id": "anthropic",
        "connector": "anthropic",
        "model-discovery": "none",
    })

    request = build_model_projection_request(tmp_path, "pi", enabled=True)

    assert request.entries == ()


def test_model_inventory_groups_vendor_and_harness_modes(monkeypatch, tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "anthropic-main", {
        "source-class": "remote-account",
        "vendor-id": "anthropic",
        "connector": "anthropic",
        "model-discovery": "none",
    })
    monkeypatch.setattr(providers_api, "list_provider_models", lambda _root, provider_id: {
        "ok": True,
        "models": ([{"model_id": "anthropic/claude-sonnet", "vendor_id": "anthropic"}]
                   if provider_id == "opencode" else []),
    })

    inventory = providers_api.list_model_inventory(tmp_path)

    assert inventory["vendors"] == [{
        "vendor_id": "anthropic",
        "harnesses": ["opencode"],
        "sources": [{"source_id": "anthropic-main", "enabled": True}],
        "enabled": True,
        "models": [{"model_id": "anthropic/claude-sonnet", "vendor_id": "anthropic"}],
    }]
    modes = {(row["provider_id"], row["mode"])
             for row in inventory["sources"][0]["harnesses"]}
    assert ("opencode", "native-catalog") in modes
    assert ("pi", "native-vendor") in modes
    assert ("pi", "custom-entries") not in modes


def test_vendor_enablement_updates_all_group_sources(tmp_path: Path) -> None:
    for source_id, connector in (("anthropic-a", "anthropic"), ("anthropic-b", "anthropic")):
        providers_api.model_source_add(tmp_path, source_id, {
            "source-class": "remote-account",
            "vendor-id": "anthropic",
            "connector": connector,
            "model-discovery": "none",
            "enabled": False,
        })

    result = providers_api.model_vendor_set_enabled(tmp_path, "anthropic", True)

    assert result["source_ids"] == ["anthropic-a", "anthropic-b"]
    sources = providers_api.model_source_list(tmp_path)["sources"]
    assert all(source["enabled"] for source in sources.values())


def test_holistic_apply_fans_out_only_registered_model_family(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services import models, provider_config

    calls: list[str] = []
    monkeypatch.setattr(provider_config, "is_provider_enabled", lambda _root, _pid: True)
    monkeypatch.setattr(
        models,
        "build_model_projection_request",
        lambda _root, _pid, enabled: providers_api.ModelProjectionRequest(managed_ids=()),
    )

    def _apply(_root, provider_id, *, mode, request):
        calls.append(provider_id)
        return providers_api.ModelProjectionResult(
            ok=True, supported=True, provider_id=provider_id
        )

    monkeypatch.setattr(providers_api, "manage_model_projection", _apply)

    result = providers_api.apply_model_sources(tmp_path)

    assert result["ok"] is True
    assert calls == ["opencode", "pi"]


def test_add_duplicate_rejected(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE))
    with pytest.raises(AudiaGenticError):
        providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE))


def test_update_remove_set_enabled_roundtrip(tmp_path: Path) -> None:
    providers_api.model_source_add(tmp_path, "local-a", dict(_SOURCE))

    providers_api.model_source_set_enabled(tmp_path, "local-a", False)
    listing = providers_api.model_source_list(tmp_path)
    assert listing["sources"]["local-a"]["enabled"] is False

    providers_api.model_source_update(
        tmp_path, "local-a", {"display-name": "Renamed"}
    )
    providers_api.model_source_remove(tmp_path, "local-a")
    assert providers_api.model_source_list(tmp_path)["sources"] == {}


def test_update_unknown_source_rejected(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError):
        providers_api.model_source_update(tmp_path, "nope", {"enabled": False})


def test_invalid_config_rejected_without_partial_write(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.model_source_add(
            tmp_path, "bad", {"source-class": "nope", "connector": "openai-compatible"}
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
