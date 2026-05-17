"""Provider CLI lifecycle operations — install, uninstall, repair."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.invoke.context import InvocationContext
from audiagentic.foundation.invoke.result import InvocationResult

from .descriptors.base import CliInstallRecipe, ProviderDescriptor
from .descriptors.registry import _probe_cli, all_descriptors, get_descriptor
from .surfaces.manager import apply_provider_surfaces, prune_provider_surfaces


def _descriptor(provider_id: str) -> ProviderDescriptor:
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="PRV-VALIDATION-002",
            kind="validation",
            message="unknown provider",
            details={"provider-id": provider_id},
        )
    return descriptor


def _probe_provider_cli(descriptor: ProviderDescriptor) -> dict[str, Any] | None:
    recipe = descriptor.cli_install
    if recipe and recipe.probe_fn:
        return recipe.probe_fn(descriptor)
    return _probe_cli(descriptor.cli_probe) if descriptor.cli_probe else None


def _result(
    *,
    provider_id: str,
    action: str,
    status: str,
    recipe: CliInstallRecipe | None,
    invocation: InvocationResult | None = None,
    probe: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    command = invocation.command if invocation else None
    payload: dict[str, Any] = {
        "provider-id": provider_id,
        "action": action,
        "status": status,
        "package-manager": recipe.package_manager if recipe else None,
        "package-name": recipe.package_name if recipe else None,
        "executable": recipe.executable if recipe else None,
        "command": command,
    }
    if invocation is not None and invocation.returncode is not None:
        payload.update({
            "returncode": invocation.returncode,
            "stdout": invocation.stdout,
            "stderr": invocation.stderr,
        })
    if probe is not None:
        payload["probe"] = probe
    effective_reason = reason or (invocation.reason if invocation else None)
    if effective_reason:
        payload["reason"] = effective_reason
    return payload


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
    ctx = InvocationContext(dry_run=True)
    inv = recipe.install.plan(ctx) if action == "install" else recipe.uninstall.plan(ctx)
    return _result(provider_id=provider_id, action=action, status="planned", recipe=recipe, invocation=inv)


def install_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
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
    ctx = InvocationContext(project_root=project_root, dry_run=dry_run, timeout=timeout)
    inv = recipe.install.run(ctx)
    if dry_run:
        return _result(provider_id=provider_id, action="install", status="planned", recipe=recipe, invocation=inv)
    probe = _probe_provider_cli(descriptor)
    status = "installed" if inv.status == "ok" and (probe is None or probe["available"]) else "failed"
    result = _result(provider_id=provider_id, action="install", status=status, recipe=recipe, invocation=inv, probe=probe)
    if status == "installed" and project_root is not None:
        result["surfaces"] = apply_provider_surfaces(project_root, provider_id=provider_id)
    return result


def uninstall_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
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
    ctx = InvocationContext(project_root=project_root, dry_run=dry_run, timeout=timeout)
    inv = recipe.uninstall.run(ctx)
    if dry_run:
        return _result(provider_id=provider_id, action="uninstall", status="planned", recipe=recipe, invocation=inv)
    probe = _probe_provider_cli(descriptor)
    status = "uninstalled" if inv.status == "ok" and (probe is None or not probe["available"]) else "failed"
    result = _result(provider_id=provider_id, action="uninstall", status=status, recipe=recipe, invocation=inv, probe=probe)
    if status == "uninstalled" and project_root is not None:
        result["surfaces"] = prune_provider_surfaces(project_root, provider_id=provider_id)
    return result


def repair_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
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
    result = install_provider_cli(provider_id, dry_run=dry_run, timeout=timeout, project_root=project_root)
    result["action"] = "repair"
    return result


def provision_all_provider_clis(
    action: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    project_root: Path | None = None,
) -> dict[str, Any]:
    actions = {
        "install": install_provider_cli,
        "uninstall": uninstall_provider_cli,
        "repair": repair_provider_cli,
    }
    if action not in actions:
        raise AudiaGenticError(
            code="PRV-VALIDATION-003",
            kind="validation",
            message="unsupported provider CLI provisioning action",
            details={"action": action},
        )
    results = [
        actions[action](provider_id, dry_run=dry_run, timeout=timeout, project_root=project_root)
        for provider_id in sorted(all_descriptors())
    ]
    return {
        "action": action,
        "ok": all(entry["status"] in {"installed", "uninstalled", "ok", "planned", "skipped"} for entry in results),
        "providers": results,
    }
