from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors.registry import (
    all_descriptors,
    get_descriptor,
)
from audiagentic.components.providers.workflow import provider_cli as workflow
from audiagentic.foundation.workflow.invocation import StepResult


def test_workflow_state_tables_are_consistent() -> None:
    states = workflow._PROVIDER_CLI_STATES
    sets = workflow._PROVIDER_CLI_SETS
    all_states = set(states["values"])

    assert states["initial"] in all_states, "initial state must be in values"
    for from_state, to_states in states["transitions"].items():
        assert from_state in all_states, f"transition source {from_state!r} not in values"
        for to in to_states:
            assert to in all_states, f"transition target {to!r} not in values"
    for set_name, members in sets.items():
        for s in members:
            assert s in all_states, f"set {set_name!r} contains unknown state {s!r}"


def test_all_installable_providers_support_workflow() -> None:
    for provider_id, descriptor in all_descriptors().items():
        if descriptor.cli_install is not None:
            assert workflow.supports_provider_cli_workflow(provider_id), (
                f"{provider_id} has cli_install but supports_provider_cli_workflow returned False"
            )


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

    monkeypatch.setattr(workflow, "_build_step", lambda *a, **kw: FakeStep())

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

    monkeypatch.setattr(workflow, "_build_step", lambda *a, **kw: FakeStep())

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
