from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.migration import (
    build_legacy_document,
    migrate_legacy_config,
)
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


def test_legacy_prompt_profiles_are_rejected_at_canonical_boundary() -> None:
    with pytest.raises(ValueError, match="unknown agents config keys"):
        AgentsConfigDocument.from_mapping(
            {
                "contract-version": "v2",
                "prompt_profiles": {
                    "coder": {"template_with_body": "agent-templates/coder.md"}
                },
            }
        )


def test_agents_component_does_not_depend_on_legacy_agent_jobs() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "agents"
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any("components.agent_jobs" in name for name in names):
                violations.append(f"{path}:{node.lineno}")
    assert not violations, "Agents must not import legacy agent_jobs: " + ", ".join(violations)


def test_agents_public_surfaces_have_no_legacy_agent_jobs_imports() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "agents"
    surface_parts = {"mcp", "configuration", "runtime", "delegation", "admin"}
    violations: list[str] = []
    for path in root.rglob("*.py"):
        relative_parts = set(path.relative_to(root).parts)
        if not relative_parts.intersection(surface_parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            if any("components.agent_jobs" in name for name in imported):
                violations.append(f"{path}:{node.lineno}")
    assert not violations, "Agents public surfaces must not import legacy agent_jobs: " + ", ".join(violations)


def test_agents_config_repository_round_trip_and_digest(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
    written = repo.replace(tmp_path, _document(), expected_digest=None)
    read = repo.read(tmp_path)
    assert read.document == written.document
    assert read.digest == written.digest


def test_required_agents_config_fails_closed_when_missing(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "missing.yaml", required=True)
    with pytest.raises(AgentsConfigValidationError, match="required agents config is missing"):
        repo.read(tmp_path)


def test_agents_config_requires_explicit_supported_contract_version() -> None:
    with pytest.raises(ValueError, match="contract-version is required"):
        AgentsConfigDocument.from_mapping({})
    with pytest.raises(ValueError, match="unsupported agents config contract-version"):
        AgentsConfigDocument.from_mapping({"contract-version": "v99"})


def test_agents_config_repository_compare_and_swap_rejects_stale_digest(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
    repo.replace(tmp_path, _document(), expected_digest=None)
    with pytest.raises(AgentsConfigConflictError):
        repo.replace(tmp_path, AgentsConfigDocument("v2", (), (), (), ()), expected_digest="stale")


def test_agents_config_repository_supports_trigger_records(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
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
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
    document = AgentsConfigDocument("v2", _document().prompts, _document().roles, _document().execution_profiles, (agent,))
    with pytest.raises(AgentsConfigValidationError, match=needle):
        repo.replace(tmp_path, document, expected_digest=None)


def test_repository_rejects_duplicate_entity_ids(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
    base = _document()
    duplicate = AgentsConfigDocument("v2", base.prompts + base.prompts, base.roles, base.execution_profiles, base.agents)
    with pytest.raises(AgentsConfigValidationError, match="duplicate"):
        repo.replace(tmp_path, duplicate, expected_digest=None)


def test_plain_model_instance_is_allowed(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
    document = AgentsConfigDocument(
        "v2", _document().prompts, _document().roles,
        ({"profile_id": "x", "provider_id": "local-openai", "instances": ["plain-model"]},),
        _document().agents,
    )
    assert repo.replace(tmp_path, document, expected_digest=None).document == document


def test_snapshot_nested_profile_params_cannot_be_mutated(tmp_path: Path) -> None:
    repo = AgentsConfigRepository(tmp_path / "agents.yaml")
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


def test_legacy_migration_writes_global_catalog_not_project_catalog(tmp_path: Path) -> None:
    config = tmp_path / ".audiagentic" / "config"
    config.mkdir(parents=True)
    save_yaml_file(config / "roles.yaml", {"roles": []})
    save_yaml_file(config / "execution-profiles.yaml", {"profiles": []})
    save_yaml_file(config / "agent-definitions.yaml", {"agent-definitions": []})

    global_path = global_agents_config_path()
    global_path.unlink()
    first_digest = migrate_legacy_config(tmp_path)
    second_digest = migrate_legacy_config(tmp_path)

    assert global_path.is_file()
    assert not (config / "agents.yaml").exists()
    assert second_digest == first_digest


def test_canonical_mapping_key_rejects_conflicting_embedded_identity() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        AgentsConfigDocument.from_mapping({
            "contract-version": "v2",
            "prompts": {"p": {"prompt_id": "other", "content": []}},
            "roles": {},
            "execution_profiles": {},
            "agents": {},
        })
