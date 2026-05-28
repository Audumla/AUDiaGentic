from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.providers.descriptors.registry import (
    all_descriptors,
    get_descriptor,
)
from audiagentic.components.optional.providers.workflow import provider_cli as workflow
from audiagentic.foundation.workflow.invocation import StepResult


def test_workflow_config_has_valid_provider_cli_resource_contract() -> None:
    cfg = workflow._load_provider_cli_config()
    resources = cfg.get("resources", {})
    assert resources, "provider CLI workflow must define at least one resource"

    for resource_id, resource in resources.items():
        assert resource_id.startswith("provider-cli.")
        assert isinstance(resource.get("extends"), str)
        assert isinstance(resource.get("recipes"), dict) and resource["recipes"]
        assert isinstance(resource.get("actions"), dict) and resource["actions"]
        for action_name, action in resource["actions"].items():
            recipe_name = action.get("recipe")
            assert recipe_name in resource["recipes"], (
                f"{resource_id}.{action_name} points to missing recipe '{recipe_name}'"
            )
            for field in (
                "start_state",
                "success_state",
                "failure_state",
                "legacy_success_status",
                "initial_state",
            ):
                assert isinstance(action.get(field), str) and action[field]
            assert isinstance(action.get("probe_available"), bool)


def test_all_installable_providers_use_workflow() -> None:
    installable = {
        provider_id
        for provider_id, descriptor in all_descriptors().items()
        if descriptor.cli_install is not None
    }
    workflow_backed = {
        resource_id.removeprefix("provider-cli.")
        for resource_id in workflow._load_provider_cli_config().get("resources", {})
    }
    assert workflow_backed == installable


def test_workflow_plan_renders_install_command_from_yaml() -> None:
    descriptor = get_descriptor("codex")
    assert descriptor is not None
    result = workflow.workflow_provider_cli_plan("codex", action="install", descriptor=descriptor)

    assert result.status == "planned"
    install_step = result.outputs["install"]
    assert install_step["command"] == ["npm", "install", "-g", "@openai/codex"]


def test_workflow_plan_renders_uninstall_command_from_yaml() -> None:
    descriptor = get_descriptor("codex")
    assert descriptor is not None
    result = workflow.workflow_provider_cli_plan("codex", action="uninstall", descriptor=descriptor)

    assert result.status == "planned"
    uninstall_step = result.outputs["uninstall"]
    assert uninstall_step["command"] == ["npm", "uninstall", "-g", "@openai/codex"]


def test_workflow_plan_renders_callable_step_for_pi() -> None:
    descriptor = get_descriptor("pi")
    assert descriptor is not None

    result = workflow.workflow_provider_cli_plan("pi", action="install", descriptor=descriptor)

    assert result.status == "planned"
    assert result.outputs["install"]["callable"] == "_pi_install"


def test_workflow_run_install_emits_state_transitions(monkeypatch, tmp_path: Path) -> None:
    descriptor = get_descriptor("codex")
    assert descriptor is not None

    class FakeStep:
        id = "install"

        def plan(self, context):
            return StepResult(status="planned")

        def run(self, context, answers=None):
            return StepResult(
                status="ok",
                outputs={"command": ["npm", "install", "-g", "@openai/codex"], "returncode": 0},
            )

    monkeypatch.setattr(workflow, "_step_for_action", lambda *a, **kw: FakeStep())

    result, probe, status, events = workflow.workflow_provider_cli_run(
        "codex",
        action="install",
        descriptor=descriptor,
        dry_run=False,
        timeout=30,
        project_root=tmp_path,
        on_progress=None,
        probe_fn=lambda _d: {"available": True},
    )

    assert result.status == "ok"
    assert probe == {"available": True}
    assert status == "installed"
    assert [event["payload"]["new_state"] for event in events] == ["installing", "installed"]


def test_workflow_run_install_failure_transitions_to_failed(monkeypatch, tmp_path: Path) -> None:
    descriptor = get_descriptor("codex")
    assert descriptor is not None

    class FakeStep:
        id = "install"

        def plan(self, context):
            return StepResult(status="planned")

        def run(self, context, answers=None):
            return StepResult(
                status="failed",
                reason="simulated install failure",
                outputs={"command": ["npm", "install", "-g", "@openai/codex"], "returncode": 1},
            )

    monkeypatch.setattr(workflow, "_step_for_action", lambda *a, **kw: FakeStep())

    result, probe, status, events = workflow.workflow_provider_cli_run(
        "codex",
        action="install",
        descriptor=descriptor,
        dry_run=False,
        timeout=30,
        project_root=tmp_path,
        on_progress=None,
        probe_fn=lambda _d: {"available": False},
    )

    assert result.status == "failed"
    assert probe == {"available": False}
    assert status == "failed"
    assert [event["payload"]["new_state"] for event in events] == ["installing", "failed"]
