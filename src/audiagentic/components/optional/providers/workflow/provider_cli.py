from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink
from audiagentic.foundation.workflow import ItemView, StateMachine
from audiagentic.foundation.workflow.invocation import (
    CallableStep,
    ShellStep,
    WorkflowInvocationResult,
    WorkflowInvocationRunner,
)

from ..descriptors.base import ProviderDescriptor
from ..descriptors.registry import get_descriptor

_RESOURCE_KIND = "provider-cli"


def supports_provider_cli_workflow(provider_id: str) -> bool:
    descriptor = get_descriptor(provider_id)
    return descriptor is not None and descriptor.cli_install is not None


class ProviderCliWorkflowContext:
    def __init__(self, provider_id: str, state: str) -> None:
        self.root = Path.cwd()
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


# Shared state machine for all CLI providers
_PROVIDER_CLI_STATES = {
    "initial": "missing",
    "values": ["missing", "installing", "installed", "failed", "uninstalling", "uninstalled", "skipped"],
    "transitions": {
        "missing": ["installing", "skipped"],
        "installing": ["installed", "failed"],
        "installed": ["uninstalling", "failed"],
        "failed": ["installing", "skipped"],
        "uninstalling": ["uninstalled", "failed"],
        "uninstalled": ["installing"],
        "skipped": [],
    },
}
_PROVIDER_CLI_SETS = {
    "initial": {"missing"},
    "active": {"installing", "uninstalling"},
    "complete": {"installed", "uninstalled"},
    "failed": {"failed"},
    "terminal": {"skipped"},
}


def _build_context(provider_id: str, descriptor: ProviderDescriptor) -> dict[str, Any]:
    recipe = descriptor.cli_install
    return {
        "provider_id": provider_id,
        "package_manager": recipe.package_manager if recipe else None,
        "package_name": recipe.package_name if recipe else None,
        "executable": recipe.executable if recipe else None,
    }


def _build_step(
    provider_id: str,
    action: str,
    descriptor: ProviderDescriptor,
    *,
    dry_run: bool,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> ShellStep | CallableStep | None:
    recipe = descriptor.cli_install
    if recipe is None:
        return None

    if action == "install":
        install_recipe = recipe.install
    elif action == "uninstall":
        install_recipe = recipe.uninstall
    else:
        return None

    if isinstance(install_recipe, ShellStep):
        return ShellStep(
            id=action,
            command=install_recipe.command,
            dry_run=dry_run,
            timeout=timeout,
            cwd=str(project_root) if project_root is not None else None,
            progress_callback=(
                lambda message: on_progress(ComponentOutputEvent(message=message))
            ) if on_progress else None,
        )

    if isinstance(install_recipe, CallableStep):
        return CallableStep(id=action, fn=install_recipe.fn, dry_run=dry_run)

    return None


def workflow_provider_cli_plan(
    provider_id: str,
    *,
    action: str,
    descriptor: ProviderDescriptor,
) -> WorkflowInvocationResult:
    step = _build_step(provider_id, action, descriptor, dry_run=True)
    if step is None:
        return WorkflowInvocationResult(status="skipped", reason="provider has no installable CLI recipe")
    return WorkflowInvocationRunner([step]).plan(_build_context(provider_id, descriptor))


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
    step = _build_step(
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

    action_config = _action_config(action)
    current_state = action_config["initial_state"]
    workflow_ctx = ProviderCliWorkflowContext(provider_id, current_state)
    machine = StateMachine(workflow_ctx)
    resource_id = workflow_ctx._item.data["id"]
    machine.state(resource_id, action_config["start_state"], reason=action)

    invocation = WorkflowInvocationRunner([step]).run(_build_context(provider_id, descriptor))

    probe = probe_fn(descriptor)
    timed_out = invocation.reason is not None and invocation.reason.startswith("timed out after ")
    ok = (invocation.status == "ok" or timed_out) and _probe_matches(action_config, probe)
    machine.state(resource_id, action_config["success_state"] if ok else "failed", reason=invocation.reason)
    status = action_config["legacy_success_status"] if ok else "failed"
    return invocation, probe, status, workflow_ctx.events


def _probe_matches(action_config: dict[str, Any], probe: dict[str, Any] | None) -> bool:
    if probe is None:
        return True
    available = bool(probe.get("available"))
    return available is bool(action_config["probe_available"])


def _action_config(action: str) -> dict[str, Any]:
    if action == "install":
        return {
            "start_state": "installing",
            "success_state": "installed",
            "initial_state": "missing",
            "legacy_success_status": "installed",
            "probe_available": True,
        }
    if action == "uninstall":
        return {
            "start_state": "uninstalling",
            "success_state": "uninstalled",
            "initial_state": "installed",
            "legacy_success_status": "uninstalled",
            "probe_available": False,
        }
    raise ValueError(f"unknown provider CLI action: {action}")
