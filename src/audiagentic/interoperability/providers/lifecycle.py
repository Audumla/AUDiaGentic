"""Provider CLI lifecycle operations — install, uninstall, repair."""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .descriptors.base import CliInstallRecipe, ProviderDescriptor
from .descriptors.registry import _probe_cli, all_descriptors, get_descriptor

Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def _recipe_command(recipe: CliInstallRecipe, action: str) -> list[str]:
    if action == "install":
        if recipe.install_command:
            return list(recipe.install_command)
        if recipe.package_manager == "npm":
            return ["npm", "install", "-g", recipe.package_name]
        if recipe.package_manager == "uv-tool":
            return ["uv", "tool", "install", recipe.package_name]
        if recipe.package_manager == "brew":
            return ["brew", "install", recipe.package_name]
        if recipe.package_manager == "gh-extension":
            return ["gh", "extension", "install", recipe.package_name]
    if action == "uninstall":
        if recipe.uninstall_command:
            return list(recipe.uninstall_command)
        if recipe.package_manager == "npm":
            return ["npm", "uninstall", "-g", recipe.package_name]
        if recipe.package_manager == "uv-tool":
            return ["uv", "tool", "uninstall", recipe.uninstall_name or recipe.package_name]
        if recipe.package_manager == "brew":
            return ["brew", "uninstall", recipe.uninstall_name or recipe.package_name]
        if recipe.package_manager == "gh-extension":
            return ["gh", "extension", "remove", recipe.uninstall_name or recipe.package_name]
    raise AudiaGenticError(
        code="PRV-VALIDATION-001",
        kind="validation",
        message="unsupported provider CLI provisioning action",
        details={
            "package-manager": recipe.package_manager,
            "package-name": recipe.package_name,
            "action": action,
        },
    )


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
    """Probe whether the provider CLI is available.

    Dispatches to the recipe's probe_fn when present (custom provisioners),
    otherwise falls back to running the descriptor's cli_probe command.
    """
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
    command: list[str] | None = None,
    completed: subprocess.CompletedProcess[str] | None = None,
    probe: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider-id": provider_id,
        "action": action,
        "status": status,
        "package-manager": recipe.package_manager if recipe else None,
        "package-name": recipe.package_name if recipe else None,
        "executable": recipe.executable if recipe else None,
        "command": command,
    }
    if completed is not None:
        payload.update(
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )
    if probe is not None:
        payload["probe"] = probe
    if reason:
        payload["reason"] = reason
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
    command = None if recipe.install_fn else _recipe_command(recipe, action)
    return _result(
        provider_id=provider_id,
        action=action,
        status="planned",
        recipe=recipe,
        command=command,
    )


def install_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    runner: Runner = _run,
    project_root: Path | None = None,
) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    recipe = descriptor.cli_install
    if recipe is None:
        return provider_cli_plan(provider_id, "install")
    if dry_run:
        command = None if recipe.install_fn else _recipe_command(recipe, "install")
        return _result(provider_id=provider_id, action="install", status="planned", recipe=recipe, command=command)
    if recipe.install_fn:
        completed = recipe.install_fn(project_root)
        probe = _probe_provider_cli(descriptor)
        status = "installed" if completed.returncode == 0 and (probe is None or probe["available"]) else "failed"
        return _result(
            provider_id=provider_id,
            action="install",
            status=status,
            recipe=recipe,
            command=None,
            completed=completed,
            probe=probe,
        )
    command = _recipe_command(recipe, "install")
    manager = command[0]
    if shutil.which(manager) is None:
        return _result(
            provider_id=provider_id,
            action="install",
            status="failed",
            recipe=recipe,
            command=command,
            reason=f"{manager} is not available on PATH",
        )
    completed = runner(command, timeout)
    probe = _probe_provider_cli(descriptor)
    status = "installed" if completed.returncode == 0 and (probe is None or probe["available"]) else "failed"
    return _result(
        provider_id=provider_id,
        action="install",
        status=status,
        recipe=recipe,
        command=command,
        completed=completed,
        probe=probe,
    )


def uninstall_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    runner: Runner = _run,
    project_root: Path | None = None,
) -> dict[str, Any]:
    descriptor = _descriptor(provider_id)
    recipe = descriptor.cli_install
    if recipe is None:
        return provider_cli_plan(provider_id, "uninstall")
    if dry_run:
        command = None if recipe.uninstall_fn else _recipe_command(recipe, "uninstall")
        return _result(provider_id=provider_id, action="uninstall", status="planned", recipe=recipe, command=command)
    if recipe.uninstall_fn:
        completed = recipe.uninstall_fn(project_root)
        probe = _probe_provider_cli(descriptor)
        status = "uninstalled" if completed.returncode == 0 and (probe is None or not probe["available"]) else "failed"
        return _result(
            provider_id=provider_id,
            action="uninstall",
            status=status,
            recipe=recipe,
            command=None,
            completed=completed,
            probe=probe,
        )
    command = _recipe_command(recipe, "uninstall")
    manager = command[0]
    if shutil.which(manager) is None:
        return _result(
            provider_id=provider_id,
            action="uninstall",
            status="failed",
            recipe=recipe,
            command=command,
            reason=f"{manager} is not available on PATH",
        )
    completed = runner(command, timeout)
    probe = _probe_provider_cli(descriptor)
    status = "uninstalled" if completed.returncode == 0 and (probe is None or not probe["available"]) else "failed"
    return _result(
        provider_id=provider_id,
        action="uninstall",
        status=status,
        recipe=recipe,
        command=command,
        completed=completed,
        probe=probe,
    )


def repair_provider_cli(
    provider_id: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    runner: Runner = _run,
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
    result = install_provider_cli(
        provider_id,
        dry_run=dry_run,
        timeout=timeout,
        runner=runner,
        project_root=project_root,
    )
    result["action"] = "repair"
    return result


def provision_all_provider_clis(
    action: str,
    *,
    dry_run: bool = False,
    timeout: int = 300,
    runner: Runner = _run,
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
        actions[action](
            provider_id,
            dry_run=dry_run,
            timeout=timeout,
            runner=runner,
            project_root=project_root,
        )
        for provider_id in sorted(all_descriptors())
    ]
    return {
        "action": action,
        "ok": all(entry["status"] in {"installed", "uninstalled", "ok", "planned", "skipped"} for entry in results),
        "providers": results,
    }
