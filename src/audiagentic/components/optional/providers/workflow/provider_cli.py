from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink
from audiagentic.foundation.workflow import ItemView, StateMachine
from audiagentic.foundation.workflow.invocation import (
    CallableStep,
    ShellStep,
    WorkflowInvocationResult,
    WorkflowInvocationRunner,
)

from ..descriptors.base import ProviderDescriptor

_RESOURCE_KIND = "provider-cli"
_CONFIG_PATH = Path(__file__).with_name("provider_cli.yaml")


def supports_provider_cli_workflow(provider_id: str) -> bool:
    return f"provider-cli.{provider_id}" in _load_provider_cli_config().get("resources", {})


class ProviderCliWorkflowConfig:
    def __init__(self, provider_id: str) -> None:
        config = _load_provider_cli_config()
        resource = config["resources"][f"provider-cli.{provider_id}"]
        profile = config["profiles"][resource["extends"]]
        self._event_type = profile["event_type"]
        self._workflow = profile["states"]
        self._sets = {
            name: set(values) for name, values in profile.get("state_sets", {}).items()
        }

    def initial_state(self, kind: str, workflow: str | None = None) -> str:
        return self._workflow["initial"]

    def workflow_for(self, kind: str, workflow_name: str | None = None) -> dict[str, Any]:
        return {
            "values": self._workflow["values"],
            "transitions": self._workflow["transitions"],
        }

    def workflow_states(self, kind: str) -> list[str]:
        return list(self._workflow["values"])

    def state_in_set(
        self, kind: str, state: str | None, set_name: str, workflow: str | None = None
    ) -> bool:
        return state in self._sets.get(set_name, set())

    def states_in_set(self, kind: str, set_name: str, workflow: str | None = None) -> list[str]:
        return sorted(self._sets.get(set_name, set()))

    def state_priority(self, kind: str, state: str, workflow: str | None = None) -> int:
        return self._workflow["values"].index(state) if state in self._workflow["values"] else 0

    def lifecycle_action(self, name: str) -> dict[str, Any]:
        return {}

    def lifecycle_action_for_transition(
        self, kind: str, old: str, new: str, workflow: str | None = None
    ) -> tuple[str | None, dict[str, Any] | None]:
        return None, None

    def workflow_action(self, name: str) -> dict[str, Any]:
        return {}

    def state_change_event_type(self) -> str:
        return self._event_type

    def reference_fields(self, kind: str) -> list[str]:
        return []

    def reference_field_shape(self, field: str) -> str:
        return "scalar_ref"

    def reference_field_targets(self, field: str) -> list[str]:
        return []

    def seeded_reference_fields(self, kind: str) -> dict[str, str]:
        return {}

    def default_guidance(self) -> str:
        return ""

    def build_creation_extra_fields(self, kind: str, **kw: Any) -> dict[str, Any]:
        return {}

    def is_soft_deleted(self, data: dict[str, Any]) -> bool:
        return False


class ProviderCliWorkflowContext:
    def __init__(self, provider_id: str, state: str) -> None:
        self.root = Path.cwd()
        self.config = ProviderCliWorkflowConfig(provider_id)
        self.events: list[dict[str, Any]] = []
        self.saved: list[dict[str, Any]] = []
        self._item = ItemView(
            kind=_RESOURCE_KIND,
            path=Path(f"provider-cli:{provider_id}"),
            data={"id": f"provider-cli.{provider_id}", "state": state, "provider-id": provider_id},
            body="",
        )

    def lookup(self, item_id: str) -> ItemView | None:
        return self._item if item_id == self._item.data["id"] else None

    def _find(self, item_id: str) -> ItemView:
        item = self.lookup(item_id)
        if item is None:
            raise KeyError(item_id)
        return item

    def _scan(self) -> list[ItemView]:
        return [self._item]

    def save(self, item: ItemView) -> None:
        self.saved.append(dict(item.data))

    def _publish_event(
        self, event_type: str, payload: dict, metadata: dict | None = None, *, mode: Any = None
    ) -> None:
        self.events.append({"type": event_type, "payload": dict(payload), "metadata": metadata})

    def index(self) -> None:
        return None


def _load_provider_cli_config() -> dict[str, Any]:
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError(f"provider CLI workflow config missing 'workflow': {_CONFIG_PATH}")
    return workflow


def workflow_provider_cli_plan(
    provider_id: str,
    *,
    action: str,
    descriptor: ProviderDescriptor,
) -> WorkflowInvocationResult:
    action_config = _provider_action_config(provider_id, action)
    step = _step_for_action(provider_id, action, descriptor, dry_run=True)
    if step is None:
        return WorkflowInvocationResult(status="skipped", reason="provider has no installable CLI recipe")
    return WorkflowInvocationRunner([
        step,
    ]).plan(_context(provider_id, descriptor))


def workflow_provider_cli_run(
    provider_id: str,
    *,
    action: str,
    descriptor: ProviderDescriptor,
    dry_run: bool,
    timeout: int,
    project_root: Path | None,
    on_progress: ComponentOutputSink | None,
    probe_fn: Callable[[ProviderDescriptor], dict[str, Any] | None],
) -> tuple[WorkflowInvocationResult, dict[str, Any] | None, str, list[dict[str, Any]]]:
    action_config = _provider_action_config(provider_id, action)
    step = _step_for_action(
        provider_id,
        action,
        descriptor,
        dry_run=dry_run,
        timeout=timeout,
        project_root=project_root,
        on_progress=on_progress,
    )
    if step is None:
        return (
            WorkflowInvocationResult(status="skipped", reason="provider has no installable CLI recipe"),
            None,
            "skipped",
            [],
        )
    if dry_run:
        inv = workflow_provider_cli_plan(provider_id, action=action, descriptor=descriptor)
        return inv, None, "planned", []

    start_state = action_config["start_state"]
    success_state = action_config["success_state"]
    failure_state = action_config["failure_state"]
    current_state = action_config["initial_state"]
    workflow_ctx = ProviderCliWorkflowContext(provider_id, current_state)
    machine = StateMachine(workflow_ctx)
    resource_id = workflow_ctx._item.data["id"]
    machine.state(resource_id, start_state, reason=action)

    invocation = WorkflowInvocationRunner([
        step
    ]).run(_context(provider_id, descriptor))

    probe = probe_fn(descriptor)
    timed_out = invocation.reason is not None and invocation.reason.startswith("timed out after ")
    ok = (invocation.status == "ok" or timed_out) and _probe_matches(action_config, probe)
    machine.state(resource_id, success_state if ok else failure_state, reason=invocation.reason)
    status = action_config["legacy_success_status"] if ok else "failed"
    return invocation, probe, status, workflow_ctx.events


def _context(provider_id: str, descriptor: ProviderDescriptor) -> dict[str, Any]:
    resource = _provider_resource_config(provider_id)
    return {
        "provider_id": provider_id,
        "package_manager": resource.get("package-manager"),
        "package_name": resource.get("package-name"),
        "executable": resource.get("executable"),
    }


def _step_for_action(
    provider_id: str,
    action: str,
    descriptor: ProviderDescriptor,
    *,
    dry_run: bool,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> ShellStep | CallableStep | None:
    if descriptor.cli_install is None:
        return None
    resource = _provider_resource_config(provider_id)
    action_config = _provider_action_config(provider_id, action)
    recipe_name = action_config["recipe"]
    recipe = resource.get("recipes", {}).get(recipe_name)
    if not isinstance(recipe, dict):
        raise ValueError(f"provider CLI workflow recipe is not configured: {provider_id}.{recipe_name}")
    if recipe.get("type") != "shell":
        if recipe.get("type") != "callable":
            raise ValueError(f"unsupported provider CLI workflow recipe type: {recipe.get('type')}")
        target = recipe.get("target")
        if not isinstance(target, str) or ":" not in target:
            raise ValueError(f"provider CLI workflow callable recipe needs module target: {provider_id}.{recipe_name}")
        module_name, attr_name = target.split(":", 1)
        fn = getattr(importlib.import_module(module_name), attr_name)
        return CallableStep(id=action, fn=fn, dry_run=dry_run)
    command = recipe.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise ValueError(f"provider CLI workflow shell recipe needs command list: {provider_id}.{recipe_name}")
    recipe_timeout = recipe.get("timeout")
    if isinstance(recipe_timeout, int) and recipe_timeout > 0:
        timeout = recipe_timeout
    return ShellStep(
        id=action,
        command=tuple(command),
        dry_run=dry_run,
        timeout=timeout,
        cwd=str(project_root) if project_root is not None else None,
        progress_callback=(
            lambda message: on_progress(ComponentOutputEvent(message=message))
        ) if on_progress else None,
    )


def _probe_matches(action_config: dict[str, Any], probe: dict[str, Any] | None) -> bool:
    if probe is None:
        return True
    available = bool(probe.get("available"))
    return available is bool(action_config["probe_available"])


def _provider_action_config(provider_id: str, action: str) -> dict[str, Any]:
    resource = _provider_resource_config(provider_id)
    action_config = resource.get("actions", {}).get(action)
    if not isinstance(action_config, dict):
        raise ValueError(f"provider CLI workflow action is not configured: {provider_id}.{action}")
    return action_config


def _provider_resource_config(provider_id: str) -> dict[str, Any]:
    config = _load_provider_cli_config()
    resource = config["resources"][f"provider-cli.{provider_id}"]
    if not isinstance(resource, dict):
        raise ValueError(f"provider CLI workflow resource is not configured: {provider_id}")
    return resource
