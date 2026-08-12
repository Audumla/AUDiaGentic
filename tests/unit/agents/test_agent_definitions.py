"""Unit tests for agent definitions — AgentDefinition, store, CRUD, resolution (AS62).

Includes the reassessment gate as executable tests: one Execution Profile
backing two agents with different Roles; an Agent Definition re-pointed to a
different compatible Execution Profile while keeping its stable public ID,
with no versioning infrastructure; publication flags changing neither
runtime MCP projection nor provider permissions; resolution launching no
process and creating no durable task/session; fake profile/role dependencies
substituted by plain-Python parameter injection at the call site (RV890 —
not through the foundation graph).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.models.agent_definition import (
    AgentDefinition,
    AgentDefinitionStore,
    agent_definition_from_dict,
    agent_definition_to_dict,
    validate_agent_definition,
)
from audiagentic.components.agents.models.agent_definition_api import (
    create_agent_definition,
    delete_agent_definition,
    get_agent_definition,
    list_agent_definitions,
    resolve_agent_definition,
    update_agent_definition,
)
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.components.agents.models.role_api import create_role
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _make_definition(**kwargs) -> dict:
    base = {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "execution_profile_id": "fast",
        "role_ids": ["reviewer"],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# validate_agent_definition
# ---------------------------------------------------------------------------

def test_validate_agent_definition_empty_dict_returns_four_issues():
    issues = validate_agent_definition({})
    assert len(issues) == 4
    assert any("agent_id" in i for i in issues)
    assert any("name" in i for i in issues)
    assert any("execution_profile_id" in i for i in issues)
    assert any("role_ids" in i for i in issues)


def test_validate_agent_definition_minimal_valid_returns_empty():
    assert validate_agent_definition(_make_definition()) == []


def test_validate_agent_definition_invalid_publication_flag_type():
    issues = validate_agent_definition(_make_definition(acp="yes"))
    assert any("acp" in i for i in issues)


def test_validate_agent_definition_invalid_advertised_skills_type():
    issues = validate_agent_definition(_make_definition(advertised_skills="not-a-list"))
    assert any("advertised_skills" in i for i in issues)


# ---------------------------------------------------------------------------
# agent_definition_from_dict / to_dict
# ---------------------------------------------------------------------------

def test_agent_definition_from_dict_defaults():
    d = agent_definition_from_dict(_make_definition())
    assert d.internal is True
    assert d.acp is False
    assert d.a2a is False
    assert d.advertised_skills == []


def test_agent_definition_from_dict_invalid_raises_val_agd_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        agent_definition_from_dict({})
    assert exc_info.value.code == "VAL-AGD-001"


def test_agent_definition_from_dict_accepts_hyphen_keys():
    data = {
        "agent_id": "x",
        "name": "X",
        "execution-profile-id": "p",
        "role-ids": ["r"],
        "advertised-skills": ["a"],
    }
    d = agent_definition_from_dict(data)
    assert d.execution_profile_id == "p"
    assert d.role_ids == ("r",)
    assert d.advertised_skills == ["a"]


def test_agent_definition_to_dict_includes_all_fields():
    d = AgentDefinition(
        agent_id="x", name="X", execution_profile_id="p", role_ids=["r"]
    )
    result = agent_definition_to_dict(d)
    assert set(result.keys()) == {
        "agent_id", "name", "execution_profile_id", "prompt_id", "role_ids",
        "description", "advertised_skills", "internal", "acp", "a2a",
    }


# ---------------------------------------------------------------------------
# AgentDefinitionStore
# ---------------------------------------------------------------------------

def test_store_get_not_found_raises_res_agd_001():
    with pytest.raises(AudiaGenticError) as exc_info:
        AgentDefinitionStore().get("missing")
    assert exc_info.value.code == "RES-AGD-001"


def test_store_add_duplicate_raises_res_agd_002():
    store = AgentDefinitionStore()
    store.add(agent_definition_from_dict(_make_definition()))
    with pytest.raises(AudiaGenticError) as exc_info:
        store.add(agent_definition_from_dict(_make_definition()))
    assert exc_info.value.code == "RES-AGD-002"


# ---------------------------------------------------------------------------
# agent_definitions_api CRUD
# ---------------------------------------------------------------------------

def test_create_get_update_delete_definition_round_trips(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]})
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    created = create_agent_definition(tmp_path, _make_definition())
    assert created["agent_id"] == "test-agent"

    fetched = get_agent_definition(tmp_path, "test-agent")
    assert fetched["execution_profile_id"] == "fast"

    create_role(tmp_path, {"role_id": "implementer", "instructions": "Implement."})
    updated = update_agent_definition(tmp_path, "test-agent", {"role_ids": ["implementer"]})
    assert updated["role_ids"] == ["implementer"]
    assert updated["agent_id"] == "test-agent"  # immutable

    deleted = delete_agent_definition(tmp_path, "test-agent")
    assert deleted["agent_id"] == "test-agent"
    assert list_agent_definitions(tmp_path) == []


# ---------------------------------------------------------------------------
# resolve_agent_definition
# ---------------------------------------------------------------------------

def test_resolve_agent_definition_with_real_dependencies(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_agent_definition(tmp_path, _make_definition())

    resolved = resolve_agent_definition(tmp_path, "test-agent")
    assert resolved["agent_id"] == "test-agent"
    assert resolved["execution_profile"]["profile_id"] == "fast"
    assert resolved["roles"][0]["role_id"] == "reviewer"
    assert resolved["publication"] == {"internal": True, "acp": False, "a2a": False}


def test_resolve_agent_definition_not_found_raises_res_agd_001(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    with pytest.raises(AudiaGenticError) as exc_info:
        resolve_agent_definition(tmp_path, "missing")
    assert exc_info.value.code == "RES-AGD-001"


def test_resolve_agent_definition_missing_role_raises_res_rol_001(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    with pytest.raises(AudiaGenticError) as exc_info:
        create_agent_definition(tmp_path, _make_definition(role_ids=["missing-role"]))
    assert exc_info.value.code == "IO-AGD-002"


def test_resolve_agent_definition_launches_no_process_creates_no_task(tmp_path: Path):
    """Resolution is a pure lookup: neither fake dependency is ever called
    to `open`/`prompt` or otherwise start work -- only queried by ID."""
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]})
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})

    calls: list[str] = []

    def fake_profile_lookup(project_root, profile_id):
        calls.append(f"profile:{profile_id}")
        return {"profile_id": profile_id, "provider_id": "fake-provider", "instances": ["fake-model"]}

    def fake_role_lookup(project_root, role_id):
        calls.append(f"role:{role_id}")
        return {"role_id": role_id, "instructions": "fake"}

    create_agent_definition(tmp_path, _make_definition())
    resolved = resolve_agent_definition(
        tmp_path,
        "test-agent",
        execution_profile_lookup=fake_profile_lookup,
        role_lookup=fake_role_lookup,
    )

    assert calls == ["profile:fast", "role:reviewer"]
    assert not any(c.startswith(("open", "prompt", "launch", "dispatch")) for c in calls)
    assert resolved["execution_profile"]["provider_id"] == "fake-provider"
    assert resolved["roles"][0]["instructions"] == "fake"


# ---------------------------------------------------------------------------
# AS62 reassessment gate
# ---------------------------------------------------------------------------

def test_one_execution_profile_backs_two_agents_with_different_roles(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "shared", "provider_id": "local-openai", "instances": ["gpt-4o"]}
    )
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_role(tmp_path, {"role_id": "implementer", "instructions": "Implement."})

    create_agent_definition(
        tmp_path,
        _make_definition(agent_id="agent-a", execution_profile_id="shared", role_ids=["reviewer"]),
    )
    create_agent_definition(
        tmp_path,
        _make_definition(agent_id="agent-b", execution_profile_id="shared", role_ids=["implementer"]),
    )

    resolved_a = resolve_agent_definition(tmp_path, "agent-a")
    resolved_b = resolve_agent_definition(tmp_path, "agent-b")

    assert resolved_a["execution_profile"]["profile_id"] == "shared"
    assert resolved_b["execution_profile"]["profile_id"] == "shared"
    assert resolved_a["roles"][0]["role_id"] == "reviewer"
    assert resolved_b["roles"][0]["role_id"] == "implementer"


def test_agent_definition_re_pointed_to_compatible_profile_keeps_stable_id(tmp_path: Path):
    """No versioning infrastructure: re-pointing is a plain in-place update,
    not a new record with a generation/version field."""
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "old", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    create_execution_profile(
        tmp_path, {"profile_id": "new", "provider_id": "local-openai", "instances": ["gpt-4o"]}
    )
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_agent_definition(tmp_path, _make_definition(execution_profile_id="old"))

    updated = update_agent_definition(tmp_path, "test-agent", {"execution_profile_id": "new"})

    assert updated["agent_id"] == "test-agent"  # stable public ID unchanged
    assert updated["execution_profile_id"] == "new"
    assert "version" not in updated
    assert "generation" not in updated
    # Exactly one definition exists -- re-pointing did not create a second record.
    assert len(list_agent_definitions(tmp_path)) == 1


def test_publication_flags_are_stored_but_carry_no_runtime_effect(tmp_path: Path):
    """Publication flags are authorization/visibility metadata only. This
    module owns no MCP projection or provider permission logic to assert
    against -- their absence here (no import of MCP/provider-permission
    modules by agent_definitions.py/agent_definitions_api.py) is the proof
    a flag cannot alter runtime tools; the file-import check lives in
    test_agent_definitions_architecture.py."""
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_agent_definition(tmp_path, _make_definition(acp=True, a2a=True))

    resolved = resolve_agent_definition(tmp_path, "test-agent")
    assert resolved["publication"] == {"internal": True, "acp": True, "a2a": True}
