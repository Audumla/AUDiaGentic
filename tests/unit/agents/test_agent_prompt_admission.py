from pathlib import Path

from audiagentic.components.agents.gateway.admission.context import baseline_agent_template_context
from audiagentic.components.agents.gateway.admission.instructions import materialize_agent_prompt
from audiagentic.components.agents.models.prompt_definition import PromptDefinition


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


def test_baseline_context_exists_for_an_unmanaged_project(tmp_path: Path) -> None:
    external = tmp_path / "external-repository"
    external.mkdir()

    context = baseline_agent_template_context(external)

    assert context["project"]["name"] == "external-repository"
    assert context["project"]["root"] == str(external.resolve())
    assert context["source_control"]["repository"] is None
