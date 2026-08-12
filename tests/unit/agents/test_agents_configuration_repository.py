from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.migration import build_legacy_document
from audiagentic.components.agents.configuration.repository import (
    AgentsConfigConflictError,
    AgentsConfigRepository,
    AgentsConfigValidationError,
)
from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart
from audiagentic.foundation.io import save_yaml_file


def _document() -> AgentsConfigDocument:
    return AgentsConfigDocument(
        "v2",
        (PromptDefinition("p", "", (PromptTextPart("be useful"),)),),
        ({"role_id": "r", "instructions": "help"},),
        ({"profile_id": "x", "provider_id": "activity-rig", "instances": ["local"]},),
        ({"agent_id": "a", "prompt_id": "p", "role_ids": ["r"], "execution_profile_id": "x"},),
    )


def test_agents_config_path_is_canonical(tmp_path: Path) -> None:
    assert agents_config_path(tmp_path) == tmp_path / ".audiagentic" / "config" / "agents.yaml"


def test_agents_config_repository_round_trip_and_digest(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    written = repo.replace(tmp_path, _document(), expected_digest=None)
    read = repo.read(tmp_path)
    assert read.document == written.document
    assert read.digest == written.digest


def test_agents_config_repository_compare_and_swap_rejects_stale_digest(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    repo.replace(tmp_path, _document(), expected_digest=None)
    with pytest.raises(AgentsConfigConflictError):
        repo.replace(tmp_path, AgentsConfigDocument("v2", (), (), (), ()), expected_digest="stale")


def test_agents_config_repository_supports_trigger_records(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    document = AgentsConfigDocument(
        "v2", (), (), (), (),
        ({"trigger_id": "orders-created", "event_pattern": "orders.created", "enabled": True},),
    )
    snapshot = repo.replace(tmp_path, document, expected_digest=None)
    assert repo.get(tmp_path, "trigger", "orders-created")["event_pattern"] == "orders.created"
    updated = repo.put(
        tmp_path,
        "trigger",
        {"trigger_id": "orders-created", "event_pattern": "orders.*", "enabled": True},
        expected_digest=snapshot.digest,
    )
    assert repo.get(tmp_path, "trigger", "orders-created")["event_pattern"] == "orders.*"
    assert updated.digest != snapshot.digest


@pytest.mark.parametrize(
    ("agent", "needle"),
    [
        ({"agent_id": "a", "prompt_id": "missing", "role_ids": ["r"], "execution_profile_id": "x"}, "prompt_id"),
        ({"agent_id": "a", "prompt_id": "p", "role_ids": ["missing"], "execution_profile_id": "x"}, "role_ids"),
        ({"agent_id": "a", "prompt_id": "p", "role_ids": ["r"], "execution_profile_id": "missing"}, "execution_profile_id"),
    ],
)
def test_repository_rejects_missing_references(tmp_path: Path, agent: dict[str, object], needle: str) -> None:
    repo = AgentsConfigRepository()
    document = AgentsConfigDocument("v2", _document().prompts, _document().roles, _document().execution_profiles, (agent,))
    with pytest.raises(AgentsConfigValidationError, match=needle):
        repo.replace(tmp_path, document, expected_digest=None)


def test_repository_rejects_duplicate_entity_ids(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    base = _document()
    duplicate = AgentsConfigDocument("v2", base.prompts + base.prompts, base.roles, base.execution_profiles, base.agents)
    with pytest.raises(AgentsConfigValidationError, match="duplicate"):
        repo.replace(tmp_path, duplicate, expected_digest=None)


def test_plain_model_instance_is_allowed(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    document = AgentsConfigDocument(
        "v2", _document().prompts, _document().roles,
        ({"profile_id": "x", "provider_id": "local-openai", "instances": ["plain-model"]},),
        _document().agents,
    )
    assert repo.replace(tmp_path, document, expected_digest=None).document == document


def test_snapshot_nested_profile_params_cannot_be_mutated(tmp_path: Path) -> None:
    repo = AgentsConfigRepository()
    document = AgentsConfigDocument(
        "v2", _document().prompts, _document().roles,
        ({"profile_id": "x", "provider_id": "local-openai", "instances": ["plain-model"], "params": {"temperature": 0.1}},),
        _document().agents,
    )
    snapshot = repo.replace(tmp_path, document, expected_digest=None)
    with pytest.raises(TypeError):
        snapshot.document.execution_profiles[0]["params"]["temperature"] = 0.9  # type: ignore[index]


def test_legacy_role_behavior_becomes_shared_prompt(tmp_path: Path) -> None:
    config = tmp_path / ".audiagentic" / "config"
    config.mkdir(parents=True)
    save_yaml_file(config / "roles.yaml", {"contract-version": "v1", "roles": [{"role_id": "r", "instructions": "preserve me"}]})
    save_yaml_file(config / "execution-profiles.yaml", {"contract-version": "v2", "profiles": [{"profile_id": "p", "provider_id": "local-openai", "instances": ["plain"]}]})
    save_yaml_file(config / "agent-definitions.yaml", {"contract-version": "v1", "agent-definitions": [
        {"agent_id": "a", "name": "A", "execution_profile_id": "p", "role_id": "r"},
        {"agent_id": "b", "name": "B", "execution_profile_id": "p", "role_id": "r"},
    ]})
    document = build_legacy_document(tmp_path)
    assert len(document.prompts) == 1
    assert document.prompts[0].to_dict()["content"] == [{"kind": "text", "text": "preserve me"}]
    assert document.agents[0]["prompt_id"] == document.agents[1]["prompt_id"]


def test_canonical_mapping_key_rejects_conflicting_embedded_identity() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        AgentsConfigDocument.from_mapping({
            "contract-version": "v2",
            "prompts": {"p": {"prompt_id": "other", "content": []}},
            "roles": {},
            "execution_profiles": {},
            "agents": {},
        })
