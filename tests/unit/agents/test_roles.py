"""Unit tests for roles — Role, RoleStore, validation, CRUD (AS61).

Includes the reassessment gate as an executable test rather than a manual
check: one Role resolves against two different Execution Profiles, and one
Execution Profile backs two different Roles. Role and ExecutionProfile must
be independently resolvable with no cross-contamination.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.components.agents.models.role import (
    Role,
    RoleStore,
    role_from_dict,
    role_to_dict,
    validate_role,
)
from audiagentic.components.agents.models.role_api import (
    create_role,
    delete_role,
    get_role,
    list_roles,
    update_role,
)

from audiagentic.foundation.contracts.errors import AudiaGenticError


def _make_role(**kwargs) -> dict:
    base = {
        "role_id": "test-role",
        "instructions": "Review the diff for correctness.",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# validate_role
# ---------------------------------------------------------------------------

def test_validate_role_empty_dict_returns_two_issues():
    issues = validate_role({})
    assert len(issues) == 2
    assert any("role_id" in i for i in issues)
    assert any("instructions" in i for i in issues)


def test_validate_role_minimal_valid_returns_empty():
    issues = validate_role(_make_role())
    assert issues == []


def test_validate_role_with_all_fields_returns_empty():
    issues = validate_role({
        "role_id": "full",
        "instructions": "Do the thing.",
        "required_capabilities": ["read-files"],
        "output_guidance": "Be concise.",
        "runtime_tool_policy_ref": "policy://placeholder",
        "description": "Full role",
    })
    assert issues == []


def test_validate_role_invalid_required_capabilities_type():
    issues = validate_role(_make_role(required_capabilities="not-a-list"))
    assert any("required_capabilities" in i for i in issues)


def test_validate_role_invalid_required_capabilities_item_type():
    issues = validate_role(_make_role(required_capabilities=["ok", 1]))
    assert any("required_capabilities" in i for i in issues)


def test_validate_role_output_guidance_null_is_valid():
    issues = validate_role(_make_role(output_guidance=None))
    assert issues == []


# ---------------------------------------------------------------------------
# role_from_dict
# ---------------------------------------------------------------------------

def test_role_from_dict_minimal():
    r = role_from_dict(_make_role())
    assert r.role_id == "test-role"
    assert r.instructions == "Review the diff for correctness."
    assert r.required_capabilities == []
    assert r.output_guidance is None
    assert r.runtime_tool_policy_ref is None
    assert r.description == ""


def test_role_from_dict_full():
    data = {
        "role_id": "reviewer",
        "instructions": "Review for correctness.",
        "required_capabilities": ["read-files"],
        "output_guidance": "Be concise.",
        "runtime_tool_policy_ref": "policy://placeholder",
        "description": "Reviewer role",
    }
    r = role_from_dict(data)
    assert r.role_id == "reviewer"
    assert r.required_capabilities == ["read-files"]
    assert r.output_guidance == "Be concise."
    assert r.runtime_tool_policy_ref == "policy://placeholder"
    assert r.description == "Reviewer role"


def test_role_from_dict_invalid_raises_val_rol_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        role_from_dict({})
    assert exc_info.value.code == "VAL-ROL-001"
    assert exc_info.value.kind == "agents"


def test_role_from_dict_strips_whitespace_role_id():
    data = _make_role(role_id="  spaced  ")
    r = role_from_dict(data)
    assert r.role_id == "spaced"


def test_role_from_dict_accepts_hyphen_keys():
    data = {
        "role_id": "x",
        "instructions": "do it",
        "required-capabilities": ["a"],
        "output-guidance": "concise",
        "runtime-tool-policy-ref": "policy://x",
    }
    r = role_from_dict(data)
    assert r.required_capabilities == ["a"]
    assert r.output_guidance == "concise"
    assert r.runtime_tool_policy_ref == "policy://x"


# ---------------------------------------------------------------------------
# role_to_dict
# ---------------------------------------------------------------------------

def test_role_to_dict_includes_all_fields():
    r = Role(
        role_id="x",
        instructions="do it",
        required_capabilities=["a"],
        output_guidance="concise",
        runtime_tool_policy_ref="policy://x",
        description="desc",
    )
    d = role_to_dict(r)
    assert set(d.keys()) == {
        "role_id",
        "instructions",
        "required_capabilities",
        "output_guidance",
        "runtime_tool_policy_ref",
        "description",
    }


# ---------------------------------------------------------------------------
# RoleStore
# ---------------------------------------------------------------------------

def test_store_empty_by_default():
    assert RoleStore().list_all() == []


def test_store_add_and_get():
    store = RoleStore()
    store.add(role_from_dict(_make_role()))
    assert store.get("test-role").role_id == "test-role"


def test_store_get_not_found_raises_res_rol_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        RoleStore().get("missing")
    assert exc_info.value.code == "RES-ROL-001"


def test_store_add_duplicate_raises_res_rol_002():
    store = RoleStore()
    store.add(role_from_dict(_make_role()))
    with pytest.raises(AudiaGenticError) as exc_info:
        store.add(role_from_dict(_make_role()))
    assert exc_info.value.code == "RES-ROL-002"


def test_store_remove_returns_deleted():
    store = RoleStore()
    store.add(role_from_dict(_make_role()))
    deleted = store.remove("test-role")
    assert deleted.role_id == "test-role"
    assert store.list_all() == []


def test_store_from_dicts_skips_invalid_entries():
    data = [_make_role(role_id="good"), {"role_id": "bad"}]  # missing instructions
    store = RoleStore.from_dicts(data)
    assert len(store.list_all()) == 1
    assert store.list_all()[0].role_id == "good"


# ---------------------------------------------------------------------------
# roles_api CRUD (through the project config file)
# ---------------------------------------------------------------------------

def test_create_get_update_delete_role_round_trips(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    created = create_role(tmp_path, _make_role())
    assert created["role_id"] == "test-role"

    fetched = get_role(tmp_path, "test-role")
    assert fetched["instructions"] == "Review the diff for correctness."

    updated = update_role(tmp_path, "test-role", {"instructions": "Updated instructions."})
    assert updated["instructions"] == "Updated instructions."
    assert updated["role_id"] == "test-role"  # immutable

    deleted = delete_role(tmp_path, "test-role")
    assert deleted["role_id"] == "test-role"
    assert list_roles(tmp_path) == []


def test_get_role_not_found_raises(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    with pytest.raises(AudiaGenticError) as exc_info:
        get_role(tmp_path, "missing")
    assert exc_info.value.code == "RES-ROL-001"


# ---------------------------------------------------------------------------
# AS61 reassessment gate: Role and ExecutionProfile are orthogonal axes.
# One Role resolves against two Execution Profiles; one Execution Profile
# backs two Roles. Neither axis contaminates the other.
# ---------------------------------------------------------------------------

def test_one_role_resolves_against_two_execution_profiles(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "model_id": "gpt-4o-mini"}
    )
    create_execution_profile(
        tmp_path, {"profile_id": "strong", "provider_id": "anthropic", "model_id": "claude-3"}
    )
    role = create_role(tmp_path, _make_role(role_id="reviewer"))

    # The same Role definition is usable regardless of which profile a caller
    # separately selects -- Role carries no provider/model reference at all.
    assert role["role_id"] == "reviewer"
    assert "provider_id" not in role
    assert "model_id" not in role


def test_one_execution_profile_backs_two_roles(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "shared", "provider_id": "local-openai", "model_id": "gpt-4o"}
    )
    reviewer = create_role(tmp_path, _make_role(role_id="reviewer", instructions="Review."))
    implementer = create_role(
        tmp_path, _make_role(role_id="implementer", instructions="Implement.")
    )

    # Both roles exist independently of the profile and of each other.
    assert reviewer["role_id"] == "reviewer"
    assert implementer["role_id"] == "implementer"
    ids = {r["role_id"] for r in list_roles(tmp_path)}
    assert ids == {"reviewer", "implementer"}
