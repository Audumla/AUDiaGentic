"""Provider CLI lifecycle operations — install, uninstall, repair, reconcile."""
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
    from audiagentic.foundation.config.provider_config import patch_provider_config

    seed: dict[str, Any] = {
        "enabled": enabled,
        "install-mode": descriptor.install_mode,
        "access-mode": descriptor.access_mode,
    }
    # Only patch — existing keys (default-model, prompt-surface, etc.) are preserved.
    patch_provider_config(project_root, provider_id, seed)


def reconcile_provider(
    provider_id: str,
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Bring providers.yaml in sync with the actual host state for one provider.

    Probes the host, reads the current config, then:
    - binary present but not enabled  → enable + apply surfaces
    - binary absent but still enabled → disable + prune surfaces
    - already in sync                 → no-op, reports current state
    """
    from audiagentic.foundation.config.provider_config import (
        load_provider_config,
        set_provider_enabled,
    )

    descriptor = _descriptor(provider_id)
    probe = _probe_provider_cli(descriptor)
    cli_available = bool(probe and probe["available"])

    try:
        provider_config = load_provider_config(project_root)
    except AudiaGenticError:
        # Fall back to raw read — reconcile only needs the enabled flag, not full validation.
        import yaml as _yaml

        from audiagentic.foundation.config.provider_config import _providers_yaml_path
        _path = _providers_yaml_path(project_root)
        provider_config = (_yaml.safe_load(_path.read_text(encoding="utf-8")) or {}) if _path.exists() else {}
    provider_cfg = provider_config.get("providers", {}).get(provider_id, {})
    currently_enabled = bool(provider_cfg.get("enabled", False))

    action_taken: str
    surfaces_result: dict[str, Any] | None = None

    if cli_available and not currently_enabled:
        _seed_provider_config(project_root, provider_id, descriptor, enabled=True)
        surfaces_result = apply_provider_surfaces(project_root, provider_id=provider_id)
        action_taken = "enabled"
    elif not cli_available and currently_enabled:
        set_provider_enabled(project_root, provider_id, enabled=False)
        surfaces_result = prune_provider_surfaces(project_root, provider_id=provider_id)
        action_taken = "disabled"
    else:
        action_taken = "ok"

    result: dict[str, Any] = {
        "provider-id": provider_id,
        "action": "reconcile",
        "status": action_taken,
        "cli-available": cli_available,
        "was-enabled": currently_enabled,
        "probe": probe,
    }
    if surfaces_result is not None:
        result["surfaces"] = surfaces_result
    return result


def reconcile_all_providers(*, project_root: Path) -> dict[str, Any]:
    """Reconcile every registered provider against host state.

    VS Code extension providers (install_method='vscode') are skipped — their
    availability is determined by the VS Code host, not by subprocess probing,
    and running 'code' as a subprocess at launch time can inadvertently open
    the VS Code GUI on some platforms.
    """
    descriptors = all_descriptors()
    results = [
        reconcile_provider(provider_id, project_root=project_root)
        for provider_id, desc in sorted(descriptors.items())
        if not (desc.cli_install and desc.cli_install.package_manager == "vscode")
    ]
    return {
        "action": "reconcile",
        "ok": True,
        "providers": results,
    }


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
