"""Provider reconciliation — bring providers.yaml in sync with host state."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.output import ComponentOutputEvent, ComponentOutputSink

from ..descriptors.registry import all_descriptors

logger = logging.getLogger(__name__)


def _sync_provider_mcp(project_root: Path, on_progress: ComponentOutputSink | None = None) -> None:
    """Sync all component MCP servers to provider configs — adds missing, removes stale.

    Delegates to sync_all_provider_mcp_servers, which iterates every installed +
    enabled component and projects its managed MCP entries to all MCP-capable
    providers (active or not).
    """
    from .lifecycle.lifecycle import _emit

    try:
        from .mcp.mcp_sync import sync_all_provider_mcp_servers

        sync_all_provider_mcp_servers(project_root)
        _emit(on_progress, "MCP server configs synced")
    except Exception:  # noqa: BLE001
        logger.warning("MCP server config sync failed", exc_info=True)
        _emit(on_progress, "MCP server config sync failed (non-fatal)", level="warning")


def _reconcile_model_projection(
    provider_id: str,
    project_root: Path,
    *,
    enabled: bool,
    on_progress: ComponentOutputSink | None = None,
) -> None:
    """Sync managed model entries for one provider (MO02 step 6, non-fatal).

    Enabled providers receive the desired entries through the typed public
    model-projection family; disabled providers prune their owned ids through
    the same seam. Providers without a declared implementation are a clean
    skip.
    """
    from .lifecycle.lifecycle import _emit

    try:
        from audiagentic.components.providers.descriptors.registry import get_descriptor
        from audiagentic.components.providers.providers_api import manage_model_projection

        from .catalog.models import (
            build_model_projection_request,
        )

        descriptor = get_descriptor(provider_id)
        if descriptor is None or descriptor.automation_capability("model-projection") is None:
            return
        request = build_model_projection_request(project_root, provider_id, enabled=enabled)
        result = manage_model_projection(
            project_root,
            provider_id,
            mode="apply" if enabled else "prune",
            request=request,
        )
        if result.updated or result.removed:
            _emit(on_progress, f"Model config synced for {provider_id}")
    except Exception:  # noqa: BLE001
        logger.warning(
            "Model config sync failed for %s",
            provider_id,
            exc_info=True,
            extra={"provider": provider_id},
        )
        _emit(
            on_progress, f"Model config sync failed for {provider_id} (non-fatal)", level="warning"
        )


def _sync_host_extensions(
    project_root: Path, on_progress: ComponentOutputSink | None = None
) -> None:
    """Sync each detected host's extensions manifest from provider host capabilities."""
    from .host.host_adapter import all_host_adapters
    from .lifecycle.lifecycle import _emit

    try:
        for host_id, adapter in all_host_adapters().items():
            if not adapter.detect_workspace(project_root):
                continue

            all_extensions = []
            for _provider_id, descriptor in all_descriptors().items():
                all_extensions.extend(descriptor.host_extensions(host_id))

            if not all_extensions:
                continue

            from audiagentic.components.providers.surfaces.extensions_json import (
                write_extensions_json,
            )

            write_extensions_json(project_root, tuple(all_extensions), host_id=host_id)
            _emit(on_progress, f"{adapter.display_name or host_id} extensions manifest synced")
    except Exception:  # noqa: BLE001
        logger.warning("Host extensions manifest sync failed", exc_info=True)
        _emit(on_progress, "Host extensions manifest sync failed (non-fatal)", level="warning")


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
    from .config.provider_config import (
        is_provider_enabled,
        set_provider_enabled,
    )
    from .lifecycle.lifecycle import (
        _descriptor as _get_descriptor,
    )
    from .lifecycle.lifecycle import (
        _emit,
        _seed_provider_config,
        probe_provider_cli,
    )

    _emit(on_progress, f"Probing {provider_id}...")
    descriptor = _get_descriptor(provider_id)
    probe = probe_provider_cli(descriptor)
    cli_available = bool(probe and probe["available"])
    _emit(on_progress, f"CLI {'available' if cli_available else 'not found'}")

    # Enablement is feature state, independent of providers.yaml.
    currently_enabled = is_provider_enabled(project_root, provider_id)

    action_taken: str
    surfaces_result: dict[str, Any] | None = None

    if cli_available and not currently_enabled:
        _emit(on_progress, f"Enabling {provider_id} and applying surfaces")
        _seed_provider_config(project_root, provider_id, descriptor, enabled=True)
        from ..providers_api import operate_provider_surface
        from .lifecycle.lifecycle import _build_surface_request

        surface_result = operate_provider_surface(
            project_root,
            provider_id,
            mode="apply",
            request=_build_surface_request(project_root, provider_id),
        )
        surfaces_result = surface_result.to_mapping()
        _sync_provider_mcp(project_root, on_progress)
        _reconcile_model_projection(
            provider_id, project_root, enabled=True, on_progress=on_progress
        )
        _sync_host_extensions(project_root, on_progress)
        action_taken = "enabled"
        if fetch_catalog and descriptor.fetch_catalog_fn is not None:
            try:
                _emit(on_progress, f"Fetching model catalog for {provider_id}")
                from .catalog.catalog import (
                    fetch_provider_catalog,
                )

                fetch_provider_catalog(provider_id, project_root=project_root)
            except Exception:  # noqa: BLE001
                _emit(
                    on_progress,
                    f"Catalog fetch failed for {provider_id} (non-fatal)",
                    level="warning",
                )
        elif descriptor.fetch_catalog_fn is not None:
            _emit(
                on_progress,
                f"Skipping catalog fetch for {provider_id} — use refresh_provider_catalog to update",
            )
    elif not cli_available and currently_enabled:
        _emit(on_progress, f"Disabling {provider_id} — CLI not found")
        set_provider_enabled(project_root, provider_id, enabled=False)
        from ..providers_api import operate_provider_surface
        from .lifecycle.lifecycle import _build_surface_request

        surface_result = operate_provider_surface(
            project_root,
            provider_id,
            mode="prune",
            request=_build_surface_request(project_root, provider_id),
        )
        surfaces_result = surface_result.to_mapping()
        _reconcile_model_projection(
            provider_id, project_root, enabled=False, on_progress=on_progress
        )
        action_taken = "disabled"
    else:
        _emit(
            on_progress,
            f"{provider_id} already in sync ({('enabled' if currently_enabled else 'disabled')})",
        )
        _sync_provider_mcp(project_root, on_progress)
        _reconcile_model_projection(
            provider_id, project_root, enabled=currently_enabled, on_progress=on_progress
        )
        _sync_host_extensions(project_root, on_progress)
        action_taken = "ok"

    now_enabled = cli_available and action_taken in ("enabled", "ok")
    result: dict[str, Any] = {
        "provider-id": provider_id,
        "action": "reconcile",
        "status": action_taken,
        "cli-available": cli_available,
        "was-enabled": currently_enabled,
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
        (pid, desc)
        for pid, desc in sorted(descriptors.items())
        if not (desc.cli_install and desc.cli_install.package_manager == "vscode")
    ]
    total = float(len(eligible))
    results = []
    for i, (provider_id, _) in enumerate(eligible):
        result = reconcile_provider(
            provider_id, project_root=project_root, fetch_catalog=fetch_catalogs
        )
        results.append(result)
        if on_progress is not None:
            on_progress(
                ComponentOutputEvent(
                    message=f"[{provider_id}] reconciled: {result.get('status', 'ok')} ({i + 1}/{int(total)})",
                    progress=float(i + 1),
                    total=total,
                    data={"provider_id": provider_id, "status": result.get("status", "ok")},
                )
            )
        if on_provider is not None:
            on_provider(provider_id, result.get("status", "ok"))
    return {
        "action": "reconcile",
        "ok": True,
        "providers": results,
    }


def reconcile_all(project_root: Path) -> None:
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
        logger.warning("Background provider reconcile failed", exc_info=True)
