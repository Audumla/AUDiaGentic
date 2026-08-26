from pathlib import Path

from audiagentic.components.agents.gateway.admission.context import baseline_agent_template_context
from audiagentic.components.agents.gateway.admission.instructions import materialize_agent_prompt
from audiagentic.components.agents.models.prompt_definition import PromptDefinition
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_agent_prompt_is_rendered_from_frozen_component_context(tmp_path: Path) -> None:
    prompt = PromptDefinition.from_dict(
        {
            "prompt_id": "read-only",
            "content": [
                {
                    "kind": "text",
                    "text": "Repo {source_control.repository} on {source_control.branch}: {prompt-body}",
                }
            ],
        }
    )

    rendered = materialize_agent_prompt(
        prompt,
        prompts=(prompt,),
        config_root=tmp_path,
        template_context={
            "source_control": {"repository": "AUDiaGentic", "branch": "agent-surface-refactor"},
            "prompt-body": "reply exactly TEMPLATE-OK",
        },
    )

    assert rendered == "Repo AUDiaGentic on agent-surface-refactor: reply exactly TEMPLATE-OK"


def test_agent_prompt_includes_are_resolved_before_rendering(tmp_path: Path) -> None:
    included = PromptDefinition.from_dict(
        {"prompt_id": "included", "content": [{"kind": "text", "text": "Project {project.name}"}]}
    )
    prompt = PromptDefinition.from_dict(
        {
            "prompt_id": "main",
            "content": [
                {"kind": "include", "prompt_id": "included"},
                {"kind": "text", "text": "Task: {prompt-body}"},
            ],
        }
    )

    assert materialize_agent_prompt(
        prompt,
        prompts=(prompt, included),
        config_root=tmp_path,
        template_context={"project": {"name": "My Project"}, "prompt-body": "inspect"},
    ) == "Project My Project\nTask: inspect"


def test_prompt_file_mutation_after_admission_does_not_change_snapshot(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Initial {prompt-body}", encoding="utf-8")
    prompt = PromptDefinition.from_dict(
        {
            "prompt_id": "file-backed",
            "content": [{"kind": "file", "path": "prompt.md"}],
        }
    )
    admitted = materialize_agent_prompt(
        prompt,
        prompts=(prompt,),
        config_root=tmp_path,
        template_context={"prompt-body": "BODY"},
    )
    prompt_file.write_text("Mutated {prompt-body}", encoding="utf-8")
    assert admitted == "Initial BODY"


def test_prompt_include_mutation_after_admission_does_not_change_snapshot(tmp_path: Path) -> None:
    included = PromptDefinition.from_dict(
        {"prompt_id": "included", "content": [{"kind": "text", "text": "Initial"}]}
    )
    prompt = PromptDefinition.from_dict(
        {
            "prompt_id": "main",
            "content": [{"kind": "include", "prompt_id": "included"}],
        }
    )
    admitted = materialize_agent_prompt(
        prompt,
        prompts=(prompt, included),
        config_root=tmp_path,
        template_context={},
    )
    mutated = PromptDefinition.from_dict(
        {"prompt_id": "included", "content": [{"kind": "text", "text": "Mutated"}]}
    )
    assert admitted == "Initial"
    assert materialize_agent_prompt(
        prompt,
        prompts=(prompt, mutated),
        config_root=tmp_path,
        template_context={},
    ) == "Mutated"


def test_baseline_context_exists_for_an_unmanaged_project(tmp_path: Path) -> None:
    external = tmp_path / "external-repository"
    external.mkdir()

    context = baseline_agent_template_context(external)

    assert context["project"]["name"] == "external-repository"
    assert context["project"]["root"] == str(external.resolve())
    assert context["source_control"]["repository"] is None


def test_missing_template_placeholder_fails_at_admission(tmp_path: Path) -> None:
    prompt = PromptDefinition.from_dict(
        {
            "prompt_id": "missing",
            "content": [{"kind": "text", "text": "{does.not.exist}"}],
        }
    )
    try:
        materialize_agent_prompt(
            prompt,
            prompts=(prompt,),
            config_root=tmp_path,
            template_context={},
        )
    except AudiaGenticError as exc:
        assert exc.code == "VAL-TPL-001"
    else:
        raise AssertionError("missing template placeholder must fail closed")
