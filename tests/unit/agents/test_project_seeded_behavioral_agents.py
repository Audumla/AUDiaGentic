"""Regression coverage for AS83's seeded behavioral Agent Definitions.

Reads AUDiaGentic's own real project config
(`.audiagentic/config/{execution-profiles,roles,agent-definitions}.yaml`),
following the same pattern as `test_project_rig_tester_agent.py`: read-only
assertions against the real files, no writes into `.audiagentic/runtime/`.

These three definitions (implementer-agent, planner-agent, reviewer-agent)
were seeded via the real CRUD API from the `ag-implement`/`ag-plan`/`ag-review`
`@tag` doctrine bodies (AS83) -- the first Agent Definitions in this repo with
non-placeholder, meaningfully different role instructions.
"""
from __future__ import annotations

import pytest

from audiagentic.components.agents.models.agent_definition_api import (
    get_agent_definition,
    resolve_agent_definition,
)
from audiagentic.components.agents.models.role_api import get_role
from audiagentic.foundation.paths.package import PACKAGE_ROOT

REPO_ROOT = PACKAGE_ROOT.parent.parent

_SEEDED = [
    ("implementer-agent", "implementer"),
    ("planner-agent", "planner"),
    ("reviewer-agent", "reviewer"),
]


@pytest.mark.parametrize("role_id", [role_id for _, role_id in _SEEDED])
def test_seeded_role_has_real_non_placeholder_instructions(role_id: str) -> None:
    role = get_role(REPO_ROOT, role_id)
    assert role["instructions"]
    assert "placeholder" not in role["instructions"].lower()
    assert "no real behavior configured" not in role["instructions"].lower()


@pytest.mark.parametrize("agent_id, role_id", _SEEDED)
def test_seeded_definition_exists_and_cross_references_match(agent_id: str, role_id: str) -> None:
    definition = get_agent_definition(REPO_ROOT, agent_id)
    assert definition["execution_profile_id"] == "rig-tester"
    assert definition["role_id"] == role_id
    assert definition["internal"] is True
    assert definition["acp"] is False
    assert definition["a2a"] is False


@pytest.mark.parametrize("agent_id, role_id", _SEEDED)
def test_seeded_definition_resolves_end_to_end(agent_id: str, role_id: str) -> None:
    """Definition + profile + role resolve together -- proving the three
    real files agree with each other, not just that each individually parses."""
    resolved = resolve_agent_definition(REPO_ROOT, agent_id)
    assert resolved["agent_id"] == agent_id
    assert resolved["execution_profile"]["provider_id"] == "local-openai"
    assert resolved["execution_profile"]["model_id"] == "audiagentic-rig"
    assert resolved["role"]["role_id"] == role_id
    assert resolved["role"]["instructions"]


def test_the_three_seeded_roles_have_distinct_instructions() -> None:
    """Guards against a copy-paste seeding mistake -- each role's instructions
    must actually differ, not just its id."""
    instructions = {get_role(REPO_ROOT, role_id)["instructions"] for _, role_id in _SEEDED}
    assert len(instructions) == 3
