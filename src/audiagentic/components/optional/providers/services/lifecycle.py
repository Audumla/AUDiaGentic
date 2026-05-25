"""Provider CLI lifecycle operations — install, uninstall, repair, reconcile."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.invoke.context import InvocationContext
from audiagentic.foundation.invoke.result import InvocationResult
from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink

from ..descriptors.base import CliInstallRecipe, McpConfigSpec, ProviderDescriptor
from ..descriptors.registry import _probe_cli, all_descriptors, get_descriptor
from ..surfaces.manager import apply_provider_surfaces, prune_provider_surfaces


def _resolve_mcp_path(spec: McpConfigSpec, project_root: Path) -> Path:
    if callable(spec.config_path):
        return spec.config_path()
    return project_root / spec.config_path


def _emit(output: ComponentOutputSink | None, message: str, **data: Any) -> None:
    if output is not None:
        output(ComponentOutputEvent(message=message, data=data))


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
    ctx = InvocationContext(project_root=project_root, dry_run=dry_run, timeout=timeout, on_progress=on_progress)
    _emit(on_progress, f"Installing {provider_id}...", provider_id=provider_id, action="install")
    inv = recipe.install.run(ctx)
    if dry_run:
        return _result(provider_id=provider_id, action="install", status="planned", recipe=recipe, invocation=inv)
    _emit(on_progress, "Probing CLI availability...", provider_id=provider_id, action="install")
    probe = _probe_provider_cli_after_install(descriptor) if inv.status == "ok" else _probe_provider_cli(descriptor)
    status = "installed" if inv.status == "ok" and (probe is None or probe["available"]) else "failed"
    result = _result(provider_id=provider_id, action="install", status=status, recipe=recipe, invocation=inv, probe=probe)
    if status == "installed" and project_root is not None:
        _seed_provider_config(project_root, provider_id, descriptor, enabled=True)
        _emit(on_progress, "Applying provider surfaces...", provider_id=provider_id, action="install")
        result["surfaces"] = apply_provider_surfaces(project_root, provider_id=provider_id)
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
    ctx = InvocationContext(project_root=project_root, dry_run=dry_run, timeout=timeout, on_progress=on_progress)
    _emit(on_progress, f"Uninstalling {provider_id}...", provider_id=provider_id, action="uninstall")
    inv = recipe.uninstall.run(ctx)
    if dry_run:
        return _result(provider_id=provider_id, action="uninstall", status="planned", recipe=recipe, invocation=inv)
    _emit(on_progress, "Probing CLI availability...", provider_id=provider_id, action="uninstall")
    probe = _probe_provider_cli(descriptor)
    status = "uninstalled" if inv.status == "ok" and (probe is None or not probe["available"]) else "failed"
    result = _result(provider_id=provider_id, action="uninstall", status=status, recipe=recipe, invocation=inv, probe=probe)
    if status == "uninstalled" and project_root is not None:
        from audiagentic.components.optional.providers.services.provider_config import (
            set_provider_enabled,
        )

        set_provider_enabled(project_root, provider_id, enabled=False)
        _emit(on_progress, "Pruning provider surfaces...", provider_id=provider_id, action="uninstall")
        result["surfaces"] = prune_provider_surfaces(project_root, provider_id=provider_id)
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
    from audiagentic.components.optional.providers.services.provider_config import (
        patch_provider_config,
    )

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
    fetch_catalog: bool = False,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    """Bring providers.yaml in sync with the actual host state for one provider.

    Probes the host, reads the current config, then:
    - binary present but not enabled  → enable + apply surfaces
    - binary absent but still enabled → disable + prune surfaces
    - already in sync                 → no-op, reports current state

    fetch_catalog: if True, also fetches the model catalog when enabling a provider.
    Defaults to False — use refresh_provider_catalog / refresh_all_catalogs for that.
    """
    from audiagentic.components.optional.providers.services.provider_config import (
        load_provider_config,
        set_provider_enabled,
    )

    _emit(on_progress, f"Probing {provider_id}...")
    descriptor = _descriptor(provider_id)
    probe = _probe_provider_cli(descriptor)
    cli_available = bool(probe and probe["available"])
    _emit(on_progress, f"CLI {'available' if cli_available else 'not found'}")

    try:
        provider_config = load_provider_config(project_root)
    except AudiaGenticError:
        # Fall back to raw read — reconcile only needs the enabled flag, not full validation.
        import yaml as _yaml

        from audiagentic.components.optional.providers.services.provider_config import (
            _providers_yaml_path,
        )
        _path = _providers_yaml_path(project_root)
        provider_config = (_yaml.safe_load(_path.read_text(encoding="utf-8")) or {}) if _path.exists() else {}
    provider_cfg = provider_config.get("providers", {}).get(provider_id, {})
    currently_enabled = bool(provider_cfg.get("enabled", False))

    action_taken: str
    surfaces_result: dict[str, Any] | None = None

    if cli_available and not currently_enabled:
        _emit(on_progress, f"Enabling {provider_id} and applying surfaces")
        _seed_provider_config(project_root, provider_id, descriptor, enabled=True)
        surfaces_result = apply_provider_surfaces(project_root, provider_id=provider_id, on_progress=on_progress)
        action_taken = "enabled"
        if fetch_catalog and descriptor.fetch_catalog_fn is not None:
            try:
                _emit(on_progress, f"Fetching model catalog for {provider_id}")
                from audiagentic.components.optional.providers.services.catalog import (
                    fetch_provider_catalog,
                )
                fetch_provider_catalog(provider_id, project_root=project_root)
            except Exception:  # noqa: BLE001
                _emit(on_progress, f"Catalog fetch failed for {provider_id} (non-fatal)", level="warning")
        elif descriptor.fetch_catalog_fn is not None:
            _emit(on_progress, f"Skipping catalog fetch for {provider_id} — use refresh_provider_catalog to update")
    elif not cli_available and currently_enabled:
        _emit(on_progress, f"Disabling {provider_id} — CLI not found")
        set_provider_enabled(project_root, provider_id, enabled=False)
        surfaces_result = prune_provider_surfaces(project_root, provider_id=provider_id, on_progress=on_progress)
        action_taken = "disabled"
    else:
        _emit(on_progress, f"{provider_id} already in sync ({('enabled' if currently_enabled else 'disabled')})")
        action_taken = "ok"

    now_enabled = cli_available and action_taken in ("enabled", "ok")
    result: dict[str, Any] = {
        "provider-id": provider_id,
        "action": "reconcile",
        "status": action_taken,
        "cli-available": cli_available,
        "enabled": now_enabled,
        "probe": probe,
    }
    if surfaces_result is not None:
        result["surfaces"] = surfaces_result
    return result


def reconcile_all_providers(
    *,
    project_root: Path,
    fetch_catalogs: bool = False,
    on_provider: Callable[[str, str], None] | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    """Reconcile every registered provider against host state.

    VS Code extension providers (install_method='vscode') are skipped — their
    availability is determined by the VS Code host, not by subprocess probing,
    and running 'code' as a subprocess at launch time can inadvertently open
    the VS Code GUI on some platforms.

    on_provider(provider_id, status) is called after each provider is reconciled.
    status is "enabled", "disabled", or "ok".
    """
    descriptors = all_descriptors()
    eligible = [
        (pid, desc) for pid, desc in sorted(descriptors.items())
        if not (desc.cli_install and desc.cli_install.package_manager == "vscode")
    ]
    total = float(len(eligible))
    results = []
    for i, (provider_id, _) in enumerate(eligible):
        result = reconcile_provider(provider_id, project_root=project_root, fetch_catalog=fetch_catalogs)
        results.append(result)
        if on_progress is not None:
            on_progress(ComponentOutputEvent(
                message=f"[{provider_id}] reconciled: {result.get('status', 'ok')} ({i + 1}/{int(total)})",
                progress=float(i + 1),
                total=total,
                data={"provider_id": provider_id, "status": result.get("status", "ok")},
            ))
        if on_provider is not None:
            on_provider(provider_id, result.get("status", "ok"))
    return {
        "action": "reconcile",
        "ok": True,
        "providers": results,
    }


def add_provider_mcp_server(
    provider_id: str,
    name: str,
    command: str,
    project_root: Path,
    *,
    args: tuple[str, ...] = (),
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add or update a single MCP server entry in a provider's config, then reload."""
    from ..mcp_config import McpServerEntry, write_mcp_servers

    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    config_path = _resolve_mcp_path(spec, project_root)
    entry = McpServerEntry(name=name, command=command, args=tuple(args), env=dict(env or {}))
    write_mcp_servers(config_path, {name: entry}, spec.format)
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "server_name": name,
    }
    result.update(reload_provider_mcp(provider_id, project_root))
    return result


def remove_provider_mcp_server(
    provider_id: str,
    server_name: str,
    project_root: Path,
) -> dict[str, Any]:
    """Remove a single MCP server entry from a provider's config, then reload."""
    from ..mcp_config import remove_mcp_server

    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    config_path = _resolve_mcp_path(spec, project_root)
    removed = remove_mcp_server(config_path, server_name, spec.format)
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "server_name": server_name,
        "removed": removed,
    }
    if removed:
        result.update(reload_provider_mcp(provider_id, project_root))
    return result


def list_provider_mcp_servers(
    provider_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Return current MCP server entries from a provider's config."""
    from ..mcp_config import read_mcp_servers

    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "servers": [], "skipped": "no mcp_config defined"}

    config_path = _resolve_mcp_path(spec, project_root)
    current = read_mcp_servers(config_path, spec.format)
    return {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "format": spec.format,
        "refresh_mode": spec.refresh_mode,
        "config_exists": config_path.exists(),
        "servers": [
            {"name": e.name, "command": e.command, "args": list(e.args)}
            for e in current.values()
        ],
    }


def reload_provider_mcp(
    provider_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Signal or reload a provider after its MCP config has changed.

    file-watch providers auto-reload on file change — nothing extra needed.
    restart-required providers call reload_fn if defined, otherwise inform only.
    """
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    if spec.refresh_mode == "file-watch":
        return {
            "provider_id": provider_id,
            "ok": True,
            "auto_refreshed": True,
            "method": "file-watch",
        }

    if spec.reload_fn is not None:
        try:
            fn_result = spec.reload_fn(project_root)
        except Exception as exc:  # noqa: BLE001
            return {
                "provider_id": provider_id,
                "ok": False,
                "method": "reload-fn",
                "error": str(exc),
            }
        return {
            "provider_id": provider_id,
            "ok": True,
            "auto_refreshed": True,
            "method": "reload-fn",
            **fn_result,
        }

    return {
        "provider_id": provider_id,
        "ok": True,
        "auto_refreshed": False,
        "method": "restart-required",
        "action_needed": f"restart {descriptor.display_name} to apply MCP config changes",
    }


def reconcile_all(*, project_root: Path) -> None:
    """Generic post-install hook — reconciles all providers.

    Called from the component lifecycle as a background thread target.
    Silently ignores errors so the component install never fails due to
    provider probe failures.
    """
    from audiagentic.foundation.components.registry import is_installed
    # Guard: component may have been uninstalled before background thread runs.
    if not is_installed("providers", project_root):
        return
    try:
        reconcile_all_providers(project_root=project_root)
    except Exception:  # noqa: BLE001
        pass


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
            code="PRV-VALIDATION-003",
            kind="validation",
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
