"""Unit tests for agents_api — CRUD, load/save, seed, resolve via tmp_path."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.models import execution_profile_api as agents_api
from audiagentic.components.agents.models.execution_profile import (
    ExecutionProfileStore,
    execution_profile_from_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file


def _make_profile(**kwargs) -> dict:
    base = {
        "profile_id": "test-profile",
        "provider_id": "local-openai",
        "instances": ["gpt-4o"],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# seed_execution_profiles
# ---------------------------------------------------------------------------

def test_seed_execution_profiles_creates_file(tmp_path):
    path = global_agents_config_path()
    agents_api.seed_execution_profiles(tmp_path)
    assert path.exists()


def test_seed_execution_profiles_idempotent(tmp_path):
    agents_api.seed_execution_profiles(tmp_path)
    content_before = global_agents_config_path().read_text(encoding="utf-8")
    agents_api.seed_execution_profiles(tmp_path)
    content_after = global_agents_config_path().read_text(encoding="utf-8")
    assert content_before == content_after


def test_seed_execution_profiles_overwrites_stale_marker(tmp_path):
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Installation marker\n", encoding="utf-8")
    agents_api.seed_execution_profiles(tmp_path)
    store = agents_api.load_execution_profiles(tmp_path)
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "default"


def test_seed_execution_profiles_creates_default_profile(tmp_path):
    agents_api.seed_execution_profiles(tmp_path)
    data = load_yaml_file(global_agents_config_path())
    profiles = data.get("execution_profiles", {})
    assert len(profiles) == 1
    assert profiles["default"]["is_default"] is True


# ---------------------------------------------------------------------------
# load_execution_profiles
# ---------------------------------------------------------------------------

def test_load_execution_profiles_empty_returns_empty_store(tmp_path):
    store = agents_api.load_execution_profiles(tmp_path)
    assert store.list_all() == []


def test_load_execution_profiles_from_seed(tmp_path):
    agents_api.seed_execution_profiles(tmp_path)
    store = agents_api.load_execution_profiles(tmp_path)
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "default"


def test_load_execution_profiles_invalid_yaml_raises_io_agp_001(tmp_path):
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(":::\ninvalid: [yaml", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.load_execution_profiles(tmp_path)
    assert exc_info.value.code == "IO-EXP-001"


def test_load_execution_profiles_unsupported_contract_version_raises(tmp_path):
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("contract-version: v99\nexecution_profiles: {}\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.load_execution_profiles(tmp_path)
    assert exc_info.value.code == "VAL-EXP-004"


# ---------------------------------------------------------------------------
# save_execution_profiles
# ---------------------------------------------------------------------------

def test_save_execution_profiles_writes_file(tmp_path):
    p = execution_profile_from_dict(_make_profile())
    store = ExecutionProfileStore([p])
    agents_api.save_execution_profiles(tmp_path, store)
    path = global_agents_config_path()
    assert path.exists()
    data = load_yaml_file(path)
    assert data["contract-version"] == "v2"
    assert len(data["execution_profiles"]) == 1


def test_save_execution_profiles_overwrites_existing(tmp_path):
    p1 = execution_profile_from_dict(_make_profile(profile_id="a"))
    agents_api.save_execution_profiles(tmp_path, ExecutionProfileStore([p1]))
    p2 = execution_profile_from_dict(_make_profile(profile_id="b"))
    agents_api.save_execution_profiles(tmp_path, ExecutionProfileStore([p2]))
    data = load_yaml_file(global_agents_config_path())
    assert len(data["execution_profiles"]) == 1
    assert "b" in data["execution_profiles"]


# ---------------------------------------------------------------------------
# list_execution_profiles
# ---------------------------------------------------------------------------

def test_list_execution_profiles_empty(tmp_path):
    assert agents_api.list_execution_profiles(tmp_path) == []


def test_list_execution_profiles_returns_created_profiles(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    profiles = agents_api.list_execution_profiles(tmp_path)
    assert len(profiles) == 1
    assert profiles[0]["profile_id"] == "test-profile"


def test_list_execution_profiles_multiple(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(profile_id="a"))
    agents_api.create_execution_profile(tmp_path, _make_profile(profile_id="b"))
    profiles = agents_api.list_execution_profiles(tmp_path)
    ids = {p["profile_id"] for p in profiles}
    assert ids == {"a", "b"}


# ---------------------------------------------------------------------------
# get_execution_profile
# ---------------------------------------------------------------------------

def test_get_execution_profile_returns_profile(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.get_execution_profile(tmp_path, "test-profile")
    assert result["profile_id"] == "test-profile"
    assert result["provider_id"] == "local-openai"
    assert result["instances"] == ["gpt-4o"]


def test_get_execution_profile_not_found_raises_res_agp_001(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.get_execution_profile(tmp_path, "missing")
    assert exc_info.value.code == "RES-EXP-001"


# ---------------------------------------------------------------------------
# create_execution_profile
# ---------------------------------------------------------------------------

def test_create_execution_profile_minimal(tmp_path):
    result = agents_api.create_execution_profile(tmp_path, _make_profile())
    assert result["profile_id"] == "test-profile"
    assert result["provider_id"] == "local-openai"
    assert result["instances"] == ["gpt-4o"]


def test_create_execution_profile_persists_to_file(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    path = global_agents_config_path()
    assert path.exists()
    data = load_yaml_file(path)
    assert data["contract-version"] == "v2"
    assert len(data["execution_profiles"]) == 1


def test_create_execution_profile_with_params(tmp_path):
    result = agents_api.create_execution_profile(
        tmp_path,
        _make_profile(params={"temperature": 0.7, "max_tokens": 2048}),
    )
    assert result["params"] == {"temperature": 0.7, "max_tokens": 2048}


def test_create_execution_profile_with_description(tmp_path):
    result = agents_api.create_execution_profile(
        tmp_path,
        _make_profile(description="My custom profile"),
    )
    assert result["description"] == "My custom profile"


def test_create_execution_profile_invalid_raises_val_agp_001(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.create_execution_profile(tmp_path, {})
    assert exc_info.value.code == "VAL-EXP-001"


def test_create_execution_profile_duplicate_raises_res_agp_002(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.create_execution_profile(tmp_path, _make_profile())
    assert exc_info.value.code == "RES-EXP-002"


def test_create_execution_profile_sets_default(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(is_default=True))
    result = agents_api.get_execution_profile(tmp_path, "test-profile")
    assert result["is_default"] is True


# ---------------------------------------------------------------------------
# update_execution_profile
# ---------------------------------------------------------------------------

def test_update_execution_profile_instances(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.update_execution_profile(tmp_path, "test-profile", {"instances": ["gpt-4o-mini"]})
    assert result["instances"] == ["gpt-4o-mini"]


def test_update_execution_profile_model_alias(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.update_execution_profile(tmp_path, "test-profile", {"model_alias": "mini"})
    assert result["model_alias"] == "mini"


def test_update_execution_profile_params(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.update_execution_profile(
        tmp_path, "test-profile", {"params": {"temperature": 0.9}}
    )
    assert result["params"] == {"temperature": 0.9}


def test_update_execution_profile_description(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.update_execution_profile(tmp_path, "test-profile", {"description": "Updated"})
    assert result["description"] == "Updated"


def test_update_execution_profile_provider_id(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.update_execution_profile(tmp_path, "test-profile", {"provider_id": "anthropic"})
    assert result["provider_id"] == "anthropic"


def test_update_execution_profile_profile_id_immutable(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    agents_api.update_execution_profile(tmp_path, "test-profile", {"profile_id": "hacked"})
    result = agents_api.get_execution_profile(tmp_path, "test-profile")
    assert result["profile_id"] == "test-profile"


def test_update_execution_profile_not_found_raises_res_agp_001(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.update_execution_profile(tmp_path, "missing", {"instances": ["x"]})
    assert exc_info.value.code == "RES-EXP-001"


def test_update_execution_profile_sets_default_clears_others(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(profile_id="a", is_default=True))
    agents_api.create_execution_profile(tmp_path, _make_profile(profile_id="b", is_default=False))
    agents_api.update_execution_profile(tmp_path, "b", {"is_default": True})
    a = agents_api.get_execution_profile(tmp_path, "a")
    b = agents_api.get_execution_profile(tmp_path, "b")
    assert a["is_default"] is False
    assert b["is_default"] is True


def test_update_execution_profile_preserves_unchanged_fields(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(description="original"))
    agents_api.update_execution_profile(tmp_path, "test-profile", {"instances": ["gpt-4o-mini"]})
    result = agents_api.get_execution_profile(tmp_path, "test-profile")
    assert result["description"] == "original"
    assert result["instances"] == ["gpt-4o-mini"]


# ---------------------------------------------------------------------------
# delete_execution_profile
# ---------------------------------------------------------------------------

def test_delete_execution_profile_removes(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    result = agents_api.delete_execution_profile(tmp_path, "test-profile")
    assert result["profile_id"] == "test-profile"
    assert agents_api.list_execution_profiles(tmp_path) == []


def test_delete_execution_profile_returns_deleted_data(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(description="will be deleted"))
    result = agents_api.delete_execution_profile(tmp_path, "test-profile")
    assert result["profile_id"] == "test-profile"
    assert result["description"] == "will be deleted"


def test_delete_execution_profile_not_found_raises_res_agp_001(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.delete_execution_profile(tmp_path, "missing")
    assert exc_info.value.code == "RES-EXP-001"


def test_delete_execution_profile_persists_to_file(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    agents_api.delete_execution_profile(tmp_path, "test-profile")
    data = load_yaml_file(global_agents_config_path())
    assert data["execution_profiles"] == {}


# ---------------------------------------------------------------------------
# resolve_execution_profile
# ---------------------------------------------------------------------------

def test_resolve_execution_profile_returns_execution_data(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(model_alias="g4o", params={"temperature": 0.5}))
    result = agents_api.resolve_execution_profile(tmp_path, "test-profile")
    assert result["profile_id"] == "test-profile"
    assert result["provider_id"] == "local-openai"
    assert result["instances"] == ["gpt-4o"]
    assert result["model_alias"] == "g4o"
    assert result["params"] == {"temperature": 0.5}


def test_resolve_execution_profile_not_found_raises_res_agp_001(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.resolve_execution_profile(tmp_path, "missing")
    assert exc_info.value.code == "RES-EXP-001"


# ---------------------------------------------------------------------------
# resolve_default_execution_profile
# ---------------------------------------------------------------------------

def test_resolve_default_execution_profile_returns_default(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(profile_id="my-default", is_default=True))
    result = agents_api.resolve_default_execution_profile(tmp_path)
    assert result["profile_id"] == "my-default"


def test_resolve_default_execution_profile_no_default_raises_res_agp_003(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile(is_default=False))
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.resolve_default_execution_profile(tmp_path)
    assert exc_info.value.code == "RES-EXP-003"


def test_resolve_default_execution_profile_empty_store_raises_res_agp_003(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.resolve_default_execution_profile(tmp_path)
    assert exc_info.value.code == "RES-EXP-003"


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------

def test_crud_round_trip_create_list_get_update_delete(tmp_path):
    created = agents_api.create_execution_profile(tmp_path, _make_profile(description="new"))
    assert created["profile_id"] == "test-profile"
    profiles = agents_api.list_execution_profiles(tmp_path)
    assert len(profiles) == 1
    fetched = agents_api.get_execution_profile(tmp_path, "test-profile")
    assert fetched["description"] == "new"
    updated = agents_api.update_execution_profile(tmp_path, "test-profile", {"description": "updated"})
    assert updated["description"] == "updated"
    deleted = agents_api.delete_execution_profile(tmp_path, "test-profile")
    assert deleted["profile_id"] == "test-profile"
    assert agents_api.list_execution_profiles(tmp_path) == []


def test_create_then_get_raises_after_delete(tmp_path):
    agents_api.create_execution_profile(tmp_path, _make_profile())
    agents_api.delete_execution_profile(tmp_path, "test-profile")
    with pytest.raises(AudiaGenticError) as exc_info:
        agents_api.get_execution_profile(tmp_path, "test-profile")
    assert exc_info.value.code == "RES-EXP-001"
