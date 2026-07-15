"""Provider CLI lifecycle operations — install, uninstall, repair, reconcile."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.output import ComponentOutputEvent, ComponentOutputSink
from audiagentic.foundation.workflow.invocation import WorkflowInvocationResult

from ..descriptors.base import CliInstallRecipe, ProviderDescriptor
from ..descriptors.registry import _probe_cli, all_descriptors, get_descriptor
from ..workflow import (
    workflow_provider_cli_plan,
    workflow_provider_cli_run,
)


def _build_surface_request(project_root: Path, provider_id: str):
    """Build a GeneratedSurfaceRequest for one provider."""
    from ..contracts.generated_surface import GeneratedSurfaceRequest
    from ..surfaces.contributions import load_surface_contributions

    contributions = load_surface_contributions(project_root=project_root)
    contribution_ids = tuple(c.contribution_id for c in contributions)
    return GeneratedSurfaceRequest(
        ownership_scope=provider_id,
        contribution_ids=contribution_ids or ("__all__",),
    )

# Re-exported from reconcile module
from .reconcile import (  # noqa: F401
    _sync_provider_mcp,
    reconcile_all,
    reconcile_all_providers,
    reconcile_provider,
)


def _emit(output: ComponentOutputSink | None, message: str, **data: Any) -> None:
    if output is not None:
        output(ComponentOutputEvent(message=message, data=data))
        return
    from audiagentic.foundation.interaction import push_status

    level = str(data.pop("level", "info"))
    push_status("providers", message, level=level, details=data)


def _descriptor(provider_id: str) -> ProviderDescriptor:
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="VAL-PLFC-001",
            kind="providers",
            message="unknown provider",
            details={"provider-id": provider_id},
        )
    return descriptor


def _probe_provider_cli(descriptor: ProviderDescriptor) -> dict[str, Any] | None:
    recipe = descriptor.cli_install
    if recipe and recipe.probe_fn:
        return recipe.probe_fn(descriptor)
    return _probe_cli(descriptor.cli_probe) if descriptor.cli_probe else None


def _probe_provider_cli_after_install(descriptor: ProviderDescriptor) -> dict[str, Any] | None:
    """Probe a newly installed CLI, allowing Windows shims/PATH to settle."""
    probe = _probe_provider_cli(descriptor)
    if probe is None or probe.get("available"):
        return probe
    for _ in range(3):
        time.sleep(1)
        probe = _probe_provider_cli(descriptor)
        if probe is None or probe.get("available"):
            break
    return probe


def _result(
    *,
    provider_id: str,
    action: str,
    status: str,
    recipe: CliInstallRecipe | None,
    invocation: dict[str, Any] | None = None,
    probe: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    effective_reason = reason or (invocation.get("reason") if invocation else None)
    payload: dict[str, Any] = {
        "provider-id": provider_id,
        "action": action,
        "status": status,
        "package-manager": recipe.package_manager if recipe else None,
        "package-name": recipe.package_name if recipe else None,
        "executable": recipe.executable if recipe else None,
        "command": invocation.get("command") if invocation else None,
        **({"returncode": invocation["returncode"], "stdout": invocation.get("stdout", ""), "stderr": invocation.get("stderr", "")} if invocation and invocation.get("returncode") is not None else {}),
        **({"probe": probe} if probe else {}),
        **({"reason": effective_reason} if effective_reason else {}),
    }
    return payload


def _invocation_result_from_workflow(
    result: WorkflowInvocationResult,
    *,
    step_id: str,
) -> dict[str, Any]:
    step = result.outputs.get(step_id, {})
    return {
        "status": result.status,
        "command": step.get("command"),
        "returncode": step.get("returncode"),
        "stdout": step.get("stdout", ""),
        "stderr": step.get("stderr", ""),
        "reason": result.reason or step.get("reason"),
    }


def provider_cli_plan(provider_id: str, action: str) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    recipe = descriptor.cli_install
    if recipe is None:
        return _result(
            provider_id=provider_id,
            action=action,
            status="skipped",
            recipe=None,
            reason="provider has no installable CLI recipe",
        )
    workflow_result = workflow_provider_cli_plan(provider_id, action=action, descriptor=descriptor)
    inv = _invocation_result_from_workflow(workflow_result, step_id=action)
    return _result(provider_id=provider_id, action=action, status=inv["status"], recipe=recipe, invocation=inv)


def install_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    recipe = descriptor.cli_install
    if recipe is None:
        return _result(
            provider_id=provider_id,
            action="install",
            status="skipped",
            recipe=None,
            reason="provider has no installable CLI recipe",
        )
    _emit(on_progress, f"Installing {provider_id}...", provider_id=provider_id, action="install")
    workflow_result, probe, status, workflow_events = workflow_provider_cli_run(
        provider_id,
        action="install",
        descriptor=descriptor,
        dry_run=dry_run,
        timeout=timeout,
        project_root=project_root,
        on_progress=on_progress,
        probe_fn=_probe_provider_cli_after_install,
    )
    inv = _invocation_result_from_workflow(workflow_result, step_id="install")
    result = _result(
        provider_id=provider_id,
        action="install",
        status=status,
        recipe=recipe,
        invocation=inv,
        probe=probe,
    )
    result["workflow-events"] = workflow_events
    if status == "installed" and project_root is not None:
        _seed_provider_config(project_root, provider_id, descriptor, enabled=True)
        _emit(on_progress, "Applying provider surfaces...", provider_id=provider_id, action="install")
        from ..providers_api import operate_provider_surface

        surface_result = operate_provider_surface(
            project_root, provider_id, mode="apply",
            request=_build_surface_request(project_root, provider_id),
        )
        result["surfaces"] = surface_result.to_mapping()
        # Populate managed MCP config now that the provider is enabled; under
        # enabled-aware propagation it would otherwise wait for the next sync.
        _sync_provider_mcp(project_root, on_progress)
    _emit(on_progress, f"{provider_id}: {status}", provider_id=provider_id, action="install", status=status)
    return result


def uninstall_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    recipe = descriptor.cli_install
    if recipe is None:
        return _result(
            provider_id=provider_id,
            action="uninstall",
            status="skipped",
            recipe=None,
            reason="provider has no installable CLI recipe",
        )
    _emit(on_progress, f"Uninstalling {provider_id}...", provider_id=provider_id, action="uninstall")
    workflow_result, probe, status, workflow_events = workflow_provider_cli_run(
        provider_id,
        action="uninstall",
        descriptor=descriptor,
        dry_run=dry_run,
        timeout=timeout,
        project_root=project_root,
        on_progress=on_progress,
        probe_fn=_probe_provider_cli,
    )
    inv = _invocation_result_from_workflow(workflow_result, step_id="uninstall")
    result = _result(
        provider_id=provider_id,
        action="uninstall",
        status=status,
        recipe=recipe,
        invocation=inv,
        probe=probe,
    )
    result["workflow-events"] = workflow_events
    if status == "uninstalled" and project_root is not None:
        from audiagentic.components.providers.services.provider_config import (
            set_provider_enabled,
        )

        set_provider_enabled(project_root, provider_id, enabled=False)
        _emit(on_progress, "Pruning provider surfaces...", provider_id=provider_id, action="uninstall")
        from ..providers_api import operate_provider_surface

        surface_result = operate_provider_surface(
            project_root, provider_id, mode="prune",
            request=_build_surface_request(project_root, provider_id),
        )
        result["surfaces"] = surface_result.to_mapping()
    _emit(on_progress, f"{provider_id}: {status}", provider_id=provider_id, action="uninstall", status=status)
    return result


def repair_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    probe = _probe_provider_cli(descriptor)
    if probe and probe["available"]:
        return _result(
            provider_id=provider_id,
            action="repair",
            status="ok",
            recipe=descriptor.cli_install,
            probe=probe,
            reason="CLI already available",
        )
    result = install_provider_cli(provider_id, dry_run=dry_run, timeout=timeout, project_root=project_root, on_progress=on_progress)
    result["action"] = "repair"
    return result


def _seed_provider_config(
    project_root: Path,
    provider_id: str,
    descriptor: ProviderDescriptor,
    *,
    enabled: bool,
) -> None:
    """Write a complete minimal config block for a provider being enabled for the first time.

    Only writes fields that are absent — never overwrites existing values.
    """
    from audiagentic.components.providers.services.provider_config import (
        patch_provider_config,
        set_provider_enabled,
    )

    seed: dict[str, Any] = {
        "install-mode": descriptor.install_mode,
        "access-mode": descriptor.access_mode,
    }
    # Only patch — existing keys (default-model, prompt-surface, etc.) are preserved.
    patch_provider_config(project_root, provider_id, seed)
    # Enablement is feature state, not a providers.yaml field.
    set_provider_enabled(project_root, provider_id, enabled=enabled)


def provision_all_provider_clis(
    action: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    actions = {
        "install": install_provider_cli,
        "uninstall": uninstall_provider_cli,
        "repair": repair_provider_cli,
    }
    if action not in actions:
        raise AudiaGenticError(
            code="VAL-PLFC-002",
            kind="providers",
            message="unsupported provider CLI provisioning action",
            details={"action": action},
        )
    results = [
        actions[action](provider_id, dry_run=dry_run, timeout=timeout, project_root=project_root, on_progress=on_progress)
        for provider_id in sorted(all_descriptors())
    ]
    return {
        "action": action,
        "ok": all(entry["status"] in {"installed", "uninstalled", "ok", "planned", "skipped"} for entry in results),
        "providers": results,
    }
