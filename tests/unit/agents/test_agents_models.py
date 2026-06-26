"""Unit tests for agents models — AgentProfile, AgentProfilesStore, validation."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.models import (
    AgentProfile,
    AgentProfilesStore,
    profile_from_dict,
    profile_to_dict,
    validate_profile,
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
# validate_profile
# ---------------------------------------------------------------------------

def test_validate_profile_empty_dict_returns_three_issues():
    issues = validate_profile({})
    assert len(issues) == 3
    assert any("profile_id" in i for i in issues)
    assert any("provider_id" in i for i in issues)
    assert any("model_id" in i for i in issues)


def test_validate_profile_minimal_valid_returns_empty():
    issues = validate_profile(_make_profile())
    assert issues == []


def test_validate_profile_with_all_fields_returns_empty():
    issues = validate_profile({
        "profile_id": "full",
        "provider_id": "anthropic",
        "model_id": "claude-3",
        "model_alias": "claude",
        "params": {"temperature": 0.7},
        "is_default": True,
        "description": "Full profile",
    })
    assert issues == []


def test_validate_profile_missing_provider_id():
    issues = validate_profile({"profile_id": "x", "model_id": "m"})
    assert any("provider_id" in i for i in issues)


def test_validate_profile_missing_model_id():
    issues = validate_profile({"profile_id": "x", "provider_id": "p"})
    assert any("model_id" in i for i in issues)


def test_validate_profile_empty_profile_id():
    issues = validate_profile({"profile_id": "", "provider_id": "p", "model_id": "m"})
    assert any("profile_id" in i for i in issues)


def test_validate_profile_invalid_params_type():
    issues = validate_profile(_make_profile(params="not-a-dict"))
    assert any("params" in i for i in issues)


def test_validate_profile_invalid_is_default_type():
    issues = validate_profile(_make_profile(is_default="yes"))
    assert any("is_default" in i for i in issues)


def test_validate_profile_model_alias_null_is_valid():
    issues = validate_profile(_make_profile(model_alias=None))
    assert issues == []


# ---------------------------------------------------------------------------
# profile_from_dict
# ---------------------------------------------------------------------------

def test_profile_from_dict_minimal():
    p = profile_from_dict(_make_profile())
    assert p.profile_id == "test-profile"
    assert p.provider_id == "local-openai"
    assert p.model_id == "gpt-4o"
    assert p.model_alias is None
    assert p.params == {}
    assert p.is_default is False
    assert p.description == ""


def test_profile_from_dict_full():
    data = {
        "profile_id": "full",
        "provider_id": "anthropic",
        "model_id": "claude-3",
        "model_alias": "claude",
        "params": {"temperature": 0.7, "max_tokens": 4096},
        "is_default": True,
        "description": "Full profile",
    }
    p = profile_from_dict(data)
    assert p.profile_id == "full"
    assert p.provider_id == "anthropic"
    assert p.model_id == "claude-3"
    assert p.model_alias == "claude"
    assert p.params == {"temperature": 0.7, "max_tokens": 4096}
    assert p.is_default is True
    assert p.description == "Full profile"


def test_profile_from_dict_invalid_raises_val_agp_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        profile_from_dict({})
    assert exc_info.value.code == "VAL-AGP-001"
    assert exc_info.value.kind == "agents"


def test_profile_from_dict_strips_whitespace():
    data = {"profile_id": "  spaced  ", "provider_id": "  p  ", "model_id": "  m  "}
    p = profile_from_dict(data)
    assert p.profile_id == "spaced"
    assert p.provider_id == "p"
    assert p.model_id == "m"


def test_profile_from_dict_accepts_hyphen_is_default():
    data = {"profile_id": "x", "provider_id": "p", "model_id": "m", "is-default": True}
    p = profile_from_dict(data)
    assert p.is_default is True


def test_profile_from_dict_accepts_hyphen_model_alias():
    data = {"profile_id": "x", "provider_id": "p", "model_id": "m", "model-alias": "alias"}
    p = profile_from_dict(data)
    assert p.model_alias == "alias"


# ---------------------------------------------------------------------------
# profile_to_dict
# ---------------------------------------------------------------------------

def test_profile_to_dict_round_trips():
    data = _make_profile(params={"temperature": 0.5}, is_default=True)
    p = profile_from_dict(data)
    result = profile_to_dict(p)
    assert result["profile_id"] == "test-profile"
    assert result["provider_id"] == "local-openai"
    assert result["model_id"] == "gpt-4o"
    assert result["params"] == {"temperature": 0.5}
    assert result["is_default"] is True


def test_profile_to_dict_includes_all_fields():
    p = AgentProfile(
        profile_id="x",
        provider_id="p",
        model_id="m",
        model_alias="a",
        params={"k": "v"},
        is_default=False,
        description="desc",
    )
    d = profile_to_dict(p)
    assert set(d.keys()) == {"profile_id", "provider_id", "model_id", "model_alias", "params", "is_default", "description"}


# ---------------------------------------------------------------------------
# AgentProfilesStore
# ---------------------------------------------------------------------------

def test_store_empty_by_default():
    store = AgentProfilesStore()
    assert store.list_all() == []


def test_store_from_profiles():
    p = profile_from_dict(_make_profile())
    store = AgentProfilesStore([p])
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "test-profile"


def test_store_add_and_get():
    store = AgentProfilesStore()
    p = profile_from_dict(_make_profile())
    store.add(p)
    retrieved = store.get("test-profile")
    assert retrieved.profile_id == "test-profile"


def test_store_get_not_found_raises_res_agp_001():
    store = AgentProfilesStore()
    with pytest.raises(AudiaGenticError) as exc_info:
        store.get("missing")
    assert exc_info.value.code == "RES-AGP-001"


def test_store_add_duplicate_raises_res_agp_002():
    store = AgentProfilesStore()
    p1 = profile_from_dict(_make_profile())
    store.add(p1)
    p2 = profile_from_dict(_make_profile(profile_id="test-profile"))
    with pytest.raises(AudiaGenticError) as exc_info:
        store.add(p2)
    assert exc_info.value.code == "RES-AGP-002"


def test_store_remove_returns_deleted():
    store = AgentProfilesStore()
    p = profile_from_dict(_make_profile())
    store.add(p)
    deleted = store.remove("test-profile")
    assert deleted.profile_id == "test-profile"
    assert len(store.list_all()) == 0


def test_store_remove_not_found_raises_res_agp_001():
    store = AgentProfilesStore()
    with pytest.raises(AudiaGenticError) as exc_info:
        store.remove("missing")
    assert exc_info.value.code == "RES-AGP-001"


def test_store_default_profile():
    p1 = profile_from_dict(_make_profile(profile_id="a", is_default=False))
    p2 = profile_from_dict(_make_profile(profile_id="b", is_default=True))
    store = AgentProfilesStore([p1, p2])
    default = store.get_default()
    assert default is not None
    assert default.profile_id == "b"


def test_store_no_default_returns_none():
    p = profile_from_dict(_make_profile(is_default=False))
    store = AgentProfilesStore([p])
    assert store.get_default() is None


def test_store_add_default_clears_previous():
    p1 = profile_from_dict(_make_profile(profile_id="a", is_default=True))
    store = AgentProfilesStore([p1])
    assert store.get_default().profile_id == "a"
    p2 = profile_from_dict(_make_profile(profile_id="b", is_default=True))
    store.add(p2)
    assert store.get_default().profile_id == "b"
    assert store.get("a").is_default is False


def test_store_to_dicts():
    p = profile_from_dict(_make_profile())
    store = AgentProfilesStore([p])
    dicts = store.to_dicts()
    assert len(dicts) == 1
    assert dicts[0]["profile_id"] == "test-profile"


def test_store_from_dicts():
    data = [_make_profile(profile_id="x"), _make_profile(profile_id="y")]
    store = AgentProfilesStore.from_dicts(data)
    assert len(store.list_all()) == 2
    ids = {p.profile_id for p in store.list_all()}
    assert ids == {"x", "y"}


def test_store_from_dicts_skips_invalid_entries():
    data = [
        _make_profile(profile_id="good"),
        {"profile_id": "bad"},  # missing provider_id and model_id
    ]
    store = AgentProfilesStore.from_dicts(data)
    assert len(store.list_all()) == 1
    assert store.list_all()[0].profile_id == "good"
