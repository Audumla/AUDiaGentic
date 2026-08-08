"""Unit tests for agents models — ExecutionProfile, ExecutionProfileStore, validation."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.models.execution_profile import (
    ExecutionProfile,
    ExecutionProfileStore,
    execution_profile_from_dict,
    execution_profile_to_dict,
    validate_execution_profile,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _make_profile(**kwargs) -> dict:
    base = {
        "profile_id": "test-profile",
        "provider_id": "local-openai",
        "model_id": "gpt-4o",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# validate_execution_profile
# ---------------------------------------------------------------------------

def test_validate_execution_profile_empty_dict_returns_three_issues():
    issues = validate_execution_profile({})
    assert len(issues) == 3
    assert any("profile_id" in i for i in issues)
    assert any("provider_id" in i for i in issues)
    assert any("model_id" in i for i in issues)


def test_validate_execution_profile_minimal_valid_returns_empty():
    issues = validate_execution_profile(_make_profile())
    assert issues == []


def test_validate_execution_profile_with_all_fields_returns_empty():
    issues = validate_execution_profile({
        "profile_id": "full",
        "provider_id": "anthropic",
        "model_id": "claude-3",
        "model_alias": "claude",
        "params": {"temperature": 0.7},
        "is_default": True,
        "description": "Full profile",
    })
    assert issues == []


def test_validate_execution_profile_missing_provider_id():
    issues = validate_execution_profile({"profile_id": "x", "model_id": "m"})
    assert any("provider_id" in i for i in issues)


def test_validate_execution_profile_missing_model_id():
    issues = validate_execution_profile({"profile_id": "x", "provider_id": "p"})
    assert any("model_id" in i for i in issues)


def test_validate_execution_profile_empty_profile_id():
    issues = validate_execution_profile({"profile_id": "", "provider_id": "p", "model_id": "m"})
    assert any("profile_id" in i for i in issues)


def test_validate_execution_profile_invalid_params_type():
    issues = validate_execution_profile(_make_profile(params="not-a-dict"))
    assert any("params" in i for i in issues)


def test_validate_execution_profile_invalid_is_default_type():
    issues = validate_execution_profile(_make_profile(is_default="yes"))
    assert any("is_default" in i for i in issues)


def test_validate_execution_profile_model_alias_null_is_valid():
    issues = validate_execution_profile(_make_profile(model_alias=None))
    assert issues == []


# ---------------------------------------------------------------------------
# execution_profile_from_dict
# ---------------------------------------------------------------------------

def test_execution_profile_from_dict_minimal():
    p = execution_profile_from_dict(_make_profile())
    assert p.profile_id == "test-profile"
    assert p.provider_id == "local-openai"
    assert p.model_id == "gpt-4o"
    assert p.model_alias is None
    assert p.params == {}
    assert p.is_default is False
    assert p.description == ""
    assert p.surface_id is None


def test_execution_profile_from_dict_with_surface_id():
    data = _make_profile()
    data["surface_id"] = "pi-community-acp"
    p = execution_profile_from_dict(data)
    assert p.surface_id == "pi-community-acp"


def test_execution_profile_from_dict_accepts_hyphen_surface_id():
    data = {"profile_id": "x", "provider_id": "p", "model_id": "m", "surface-id": "pi-community-acp"}
    p = execution_profile_from_dict(data)
    assert p.surface_id == "pi-community-acp"


def test_validate_execution_profile_surface_id_empty_string_invalid():
    issues = validate_execution_profile(
        {"profile_id": "x", "provider_id": "p", "model_id": "m", "surface_id": "  "}
    )
    assert "surface_id must be a non-empty string or null" in issues


def test_validate_execution_profile_surface_id_null_is_valid():
    issues = validate_execution_profile(
        {"profile_id": "x", "provider_id": "p", "model_id": "m", "surface_id": None}
    )
    assert issues == []


def test_execution_profile_from_dict_full():
    data = {
        "profile_id": "full",
        "provider_id": "anthropic",
        "model_id": "claude-3",
        "model_alias": "claude",
        "params": {"temperature": 0.7, "max_tokens": 4096},
        "is_default": True,
        "description": "Full profile",
    }
    p = execution_profile_from_dict(data)
    assert p.profile_id == "full"
    assert p.provider_id == "anthropic"
    assert p.model_id == "claude-3"
    assert p.model_alias == "claude"
    assert p.params == {"temperature": 0.7, "max_tokens": 4096}
    assert p.is_default is True
    assert p.description == "Full profile"


def test_execution_profile_from_dict_invalid_raises_val_agp_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        execution_profile_from_dict({})
    assert exc_info.value.code == "VAL-EXP-001"
    assert exc_info.value.kind == "agents"


def test_execution_profile_from_dict_strips_whitespace():
    data = {"profile_id": "  spaced  ", "provider_id": "  p  ", "model_id": "  m  "}
    p = execution_profile_from_dict(data)
    assert p.profile_id == "spaced"
    assert p.provider_id == "p"
    assert p.model_id == "m"


def test_execution_profile_from_dict_accepts_hyphen_is_default():
    data = {"profile_id": "x", "provider_id": "p", "model_id": "m", "is-default": True}
    p = execution_profile_from_dict(data)
    assert p.is_default is True


def test_execution_profile_from_dict_accepts_hyphen_model_alias():
    data = {"profile_id": "x", "provider_id": "p", "model_id": "m", "model-alias": "alias"}
    p = execution_profile_from_dict(data)
    assert p.model_alias == "alias"


# ---------------------------------------------------------------------------
# execution_profile_to_dict
# ---------------------------------------------------------------------------

def test_execution_profile_to_dict_round_trips():
    data = _make_profile(params={"temperature": 0.5}, is_default=True)
    p = execution_profile_from_dict(data)
    result = execution_profile_to_dict(p)
    assert result["profile_id"] == "test-profile"
    assert result["provider_id"] == "local-openai"
    assert result["model_id"] == "gpt-4o"
    assert result["params"] == {"temperature": 0.5}
    assert result["is_default"] is True


def test_execution_profile_to_dict_includes_all_fields():
    p = ExecutionProfile(
        profile_id="x",
        provider_id="p",
        model_id="m",
        model_alias="a",
        params={"k": "v"},
        is_default=False,
        description="desc",
    )
    d = execution_profile_to_dict(p)
    assert set(d.keys()) == {
        "profile_id", "provider_id", "model_id", "model_alias", "params",
        "is_default", "description", "surface_id",
    }


# ---------------------------------------------------------------------------
# ExecutionProfileStore
# ---------------------------------------------------------------------------

def test_store_empty_by_default():
    store = ExecutionProfileStore()
    assert store.list_all() == []


def test_store_from_profiles():
    p = execution_profile_from_dict(_make_profile())
    store = ExecutionProfileStore([p])
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "test-profile"


def test_store_add_and_get():
    store = ExecutionProfileStore()
    p = execution_profile_from_dict(_make_profile())
    store.add(p)
    retrieved = store.get("test-profile")
    assert retrieved.profile_id == "test-profile"


def test_store_get_not_found_raises_res_agp_001():
    store = ExecutionProfileStore()
    with pytest.raises(AudiaGenticError) as exc_info:
        store.get("missing")
    assert exc_info.value.code == "RES-EXP-001"


def test_store_add_duplicate_raises_res_agp_002():
    store = ExecutionProfileStore()
    p1 = execution_profile_from_dict(_make_profile())
    store.add(p1)
    p2 = execution_profile_from_dict(_make_profile(profile_id="test-profile"))
    with pytest.raises(AudiaGenticError) as exc_info:
        store.add(p2)
    assert exc_info.value.code == "RES-EXP-002"


def test_store_remove_returns_deleted():
    store = ExecutionProfileStore()
    p = execution_profile_from_dict(_make_profile())
    store.add(p)
    deleted = store.remove("test-profile")
    assert deleted.profile_id == "test-profile"
    assert len(store.list_all()) == 0


def test_store_remove_not_found_raises_res_agp_001():
    store = ExecutionProfileStore()
    with pytest.raises(AudiaGenticError) as exc_info:
        store.remove("missing")
    assert exc_info.value.code == "RES-EXP-001"


def test_store_default_profile():
    p1 = execution_profile_from_dict(_make_profile(profile_id="a", is_default=False))
    p2 = execution_profile_from_dict(_make_profile(profile_id="b", is_default=True))
    store = ExecutionProfileStore([p1, p2])
    default = store.get_default()
    assert default is not None
    assert default.profile_id == "b"


def test_store_no_default_returns_none():
    p = execution_profile_from_dict(_make_profile(is_default=False))
    store = ExecutionProfileStore([p])
    assert store.get_default() is None


def test_store_add_default_clears_previous():
    p1 = execution_profile_from_dict(_make_profile(profile_id="a", is_default=True))
    store = ExecutionProfileStore([p1])
    assert store.get_default().profile_id == "a"
    p2 = execution_profile_from_dict(_make_profile(profile_id="b", is_default=True))
    store.add(p2)
    assert store.get_default().profile_id == "b"
    assert store.get("a").is_default is False


def test_store_to_dicts():
    p = execution_profile_from_dict(_make_profile())
    store = ExecutionProfileStore([p])
    dicts = store.to_dicts()
    assert len(dicts) == 1
    assert dicts[0]["profile_id"] == "test-profile"


def test_store_from_dicts():
    data = [_make_profile(profile_id="x"), _make_profile(profile_id="y")]
    store = ExecutionProfileStore.from_dicts(data)
    assert len(store.list_all()) == 2
    ids = {p.profile_id for p in store.list_all()}
    assert ids == {"x", "y"}


def test_store_from_dicts_skips_invalid_entries():
    data = [
        _make_profile(profile_id="good"),
        {"profile_id": "bad"},  # missing provider_id and model_id
    ]
    store = ExecutionProfileStore.from_dicts(data)
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "good"
