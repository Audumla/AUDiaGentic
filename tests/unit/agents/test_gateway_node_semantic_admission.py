"""Characterize global semantics without enabling node submission or changing hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration import resolution
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.gateway import api
from audiagentic.components.agents.gateway.admission import local_dispatch
from audiagentic.components.agents.gateway.admission import semantics as semantics_owner
from audiagentic.components.agents.gateway.admission.instructions import materialize_agent_prompt
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def catalog():
    path = global_agents_config_path()
    data = {
        "contract-version": "v2",
        "prompts": {
            "main": {
                "content": [
                    {"kind": "include", "prompt_id": "included"},
                    {"kind": "file", "path": "instructions.txt"},
                    {"kind": "text", "text": "Task: {prompt-body}"},
                ]
            },
            "included": {"content": [{"kind": "text", "text": "Original"}]},
        },
        "roles": {"reader": {"instructions": "Read only"}},
        "execution_profiles": {
            "native": {"provider_id": "codex", "instances": ["codex"], "is_default": True},
        },
        "agents": {
            "reader": {
                "name": "Reader",
                "prompt_id": "main",
                "role_ids": ["reader"],
                "execution_profile_id": "native",
            }
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (path.parent / "instructions.txt").write_text("File {prompt-body}", encoding="utf-8")
    return path, data


def render(semantics):
    return materialize_agent_prompt(
        semantics.composition.prompt,
        prompts=semantics.catalog.document.prompts,
        config_root=semantics.config_root,
        template_context={"prompt-body": "BODY"},
    )


def test_actual_semantic_resolution_never_reads_execution_local_facts(catalog, monkeypatch):
    from audiagentic.components.agents.contracts import execution_context
    from audiagentic.components.agents.gateway import instances, profiles
    from audiagentic.components.agents.gateway.admission import context, instructions
    from audiagentic.components.project import project_api
    from audiagentic.components.providers import providers_api
    from audiagentic.components.source_control import source_control_api

    def forbidden(*args, **kwargs):
        raise AssertionError("semantic resolution touched execution-local facts")

    for module, name in (
        (api, "_resolve_workspace_project_root"),
        (api, "_resolve_provider_isolation_tier"),
        (context, "baseline_agent_template_context"),
        (context, "empty_component_context"),
        (project_api, "context"),
        (source_control_api, "context"),
        (instructions, "materialize_agent_prompt"),
        (profiles, "resolve_for_admission"),
        (instances, "resolve_instance_facts"),
        (providers_api, "resolve_session_surface"),
        (providers_api, "get_provider_runtime_config_state"),
        (execution_context, "canonicalize_project_root"),
        (execution_context, "build_manifest"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    # A missing referenced file must not prevent declarative resolution.
    (catalog[0].parent / "instructions.txt").unlink()
    semantics = semantics_owner.resolve_agent_semantics("reader")
    assert semantics.execution_profile_id == "native"
    assert semantics.prompt_profile_id == "main"
    assert semantics.composition.identity.agent_id == "reader"
    assert semantics.composition.execution_profile.provider_id == "codex"
    assert semantics.composition_fingerprint == semantics.composition.identity.fingerprint
    assert (
        semantics.prompt_definition_fingerprint
        == semantics.composition.identity.prompt_definition_fingerprint
    )


def test_catalog_snapshot_is_retained_through_composition_and_rendering(catalog, monkeypatch):
    path, data = catalog
    original_read = AgentsConfigRepository.read
    original_resolve = resolution.resolve_agent_composition
    reads = []
    snapshots = []

    def read(repository, root):
        snapshot = original_read(repository, root)
        reads.append(snapshot)
        return snapshot

    def resolve(root, agent_id, *, snapshot):
        snapshots.append(snapshot)
        data["prompts"]["included"]["content"][0]["text"] = "Changed on disk"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return original_resolve(root, agent_id, snapshot=snapshot)

    monkeypatch.setattr(AgentsConfigRepository, "read", read)
    monkeypatch.setattr(resolution, "resolve_agent_composition", resolve)
    semantics = semantics_owner.resolve_agent_semantics("reader")
    assert len(reads) == 1 and len(snapshots) == 1
    assert semantics.catalog is reads[0] is snapshots[0]
    assert semantics.composition.identity.config_digest == semantics.catalog.digest
    assert render(semantics) == "Original\nFile BODY\nTask: BODY"


def test_file_bytes_change_rendered_digest_but_not_declarative_identity(catalog):
    first = semantics_owner.resolve_agent_semantics("reader")
    admitted = render(first)
    (catalog[0].parent / "instructions.txt").write_text("New file bytes", encoding="utf-8")
    second = semantics_owner.resolve_agent_semantics("reader")
    assert first.catalog.digest == second.catalog.digest
    assert first.composition.identity == second.composition.identity
    assert (
        hashlib.sha256(admitted.encode()).hexdigest()
        != hashlib.sha256(render(second).encode()).hexdigest()
    )
    assert admitted == "Original\nFile BODY\nTask: BODY"


def test_include_content_changes_catalog_and_rendering_not_parent_identity(catalog):
    path, data = catalog
    first = semantics_owner.resolve_agent_semantics("reader")
    data["prompts"]["included"]["content"][0]["text"] = "Changed include"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    second = semantics_owner.resolve_agent_semantics("reader")
    assert first.catalog.digest != second.catalog.digest
    assert first.composition_fingerprint == second.composition_fingerprint
    assert first.prompt_definition_fingerprint == second.prompt_definition_fingerprint
    assert render(first) == "Original\nFile BODY\nTask: BODY"
    assert render(second) == "Changed include\nFile BODY\nTask: BODY"


def test_file_path_is_part_of_declarative_identity(catalog):
    path, data = catalog
    first = semantics_owner.resolve_agent_semantics("reader")
    data["prompts"]["main"]["content"][1]["path"] = "other.txt"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    second = semantics_owner.resolve_agent_semantics("reader")
    assert first.composition_fingerprint != second.composition_fingerprint
    assert first.prompt_definition_fingerprint != second.prompt_definition_fingerprint


def test_missing_agent_keeps_registered_error(catalog):
    with pytest.raises(AudiaGenticError) as caught:
        semantics_owner.resolve_agent_semantics("absent")
    assert caught.value.code == "RES-AGD-001"
    assert caught.value.details == {"agent-id": "absent"}


def test_ordinary_context_failure_still_precedes_semantic_resolution(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("semantics ran before component context")

    def unavailable_context(root: Path):
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(semantics_owner, "resolve_agent_semantics", forbidden)
    with pytest.raises(RuntimeError, match="context unavailable"):
        api.submit_execution_request(
            tmp_path,
            agent_id="reader",
            prompt_body="Read",
            component_context_reader=unavailable_context,
        )


def test_ordinary_materialization_keeps_bytes_context_precedence_and_profile(
    catalog, tmp_path, monkeypatch
):
    from audiagentic.components.agents.gateway.admission import context

    path, data = catalog
    data["prompts"]["main"]["content"].append(
        {"kind": "text", "text": "{project.name}: {project.extra} / {source_control.branch}"}
    )
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    events = []
    original_resolve = semantics_owner.resolve_agent_semantics
    original_materialize = local_dispatch.materialize_local_prompt

    def component_reader(root):
        assert root == tmp_path
        events.append("component")
        return {"project": {"name": "old name", "extra": "component fact"}}

    def baseline(root, *, workspace_name):
        assert root == tmp_path and workspace_name is None
        events.append("baseline")
        return {"project": {"name": "canonical name"}, "source_control": {"branch": "main"}}

    def resolve(agent_id):
        events.append("semantics")
        return original_resolve(agent_id)

    def materialize(*args, **kwargs):
        events.append("render")
        rendered = original_materialize(*args, **kwargs)
        assert rendered.text == "Original\nFile BODY\nTask: BODY\ncanonical name: component fact / main"
        return rendered

    def stop_before_local_profile(root, profile_id, *, allow_test_fallback, profile_resolver):
        assert root == tmp_path and profile_id == "native"
        events.append("local-profile")
        raise RuntimeError("stop before provider facts")

    monkeypatch.setattr(context, "baseline_agent_template_context", baseline)
    monkeypatch.setattr(semantics_owner, "resolve_agent_semantics", resolve)
    monkeypatch.setattr(local_dispatch, "materialize_local_prompt", materialize)
    monkeypatch.setattr(local_dispatch, "resolve_local_profile", stop_before_local_profile)
    with pytest.raises(RuntimeError, match="stop before provider facts"):
        api.submit_execution_request(
            tmp_path,
            agent_id="reader",
            execution_profile_id="caller-choice",
            prompt_body="BODY",
            component_context_reader=component_reader,
        )
    assert events == ["component", "baseline", "semantics", "render", "local-profile"]
