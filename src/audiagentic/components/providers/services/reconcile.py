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


def _should_auto_enable(project_root: Path, provider_id: str) -> bool:
    """Whether a detected-but-disabled provider should be auto-enabled.

    `auto` (default) enables whatever CLI is detected, matching today's
    behavior. `allowlist`/`prompt` only auto-enable providers already present
    in `allowed-providers` — providers outside that set are left disabled
    rather than silently enabled, until something (ON03's interactive flow,
    or a direct `set_reconciliation_policy` call) explicitly decides them.
    """
    from .config.provider_config import get_reconciliation_policy

    policy = get_reconciliation_policy(project_root)
    if policy.get("mode", "auto") == "auto":
        return True
    return provider_id in set(policy.get("allowed-providers", []))


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

    if cli_available and not currently_enabled and not _should_auto_enable(project_root, provider_id):
        _emit(
            on_progress,
            f"Skipping {provider_id} — not in reconciliation-policy allowlist",
        )
        action_taken = "skipped"
    elif cli_available and not currently_enabled:
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
    status is "enabled", "disabled", "skipped" (CLI detected but excluded by the
    reconciliation-policy allowlist), or "ok".
    """
    eligible = _eligible_provider_descriptors()
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


def _eligible_provider_descriptors():
    """Same eligibility filter as reconcile_all_providers: skip VS Code extensions."""
    return [
        (pid, desc)
        for pid, desc in sorted(all_descriptors().items())
        if not (desc.cli_install and desc.cli_install.package_manager == "vscode")
    ]


def resolve_reconciliation_policy(project_root: Path) -> None:
    """Interactively resolve this project's reconciliation-policy.

    Meant to run before reconcile_all_providers, on every launch (not gated
    behind the one-time provider-reconcile stamp — see ON03 plan notes):

    - If never configured, asks the operator to choose auto/allowlist/prompt.
      A non-interactive answer (no TTY, no MCP ctx — `ask()` resolves to
      TIMED_OUT immediately) defaults to 'auto', matching pre-existing
      behavior and never blocking a scripted launch.
    - In allowlist/prompt mode, asks once per CLI-available provider not yet
      in decided-providers, and persists the accumulated decision. A provider
      left undecided this run (e.g. non-interactive) is asked again next time.
    """
    from audiagentic.foundation.interaction import ResponseStatus, ask

    from .config.provider_config import (
        get_reconciliation_policy,
        is_reconciliation_policy_configured,
        set_reconciliation_policy,
    )
    from .lifecycle.lifecycle import probe_provider_cli

    if not is_reconciliation_policy_configured(project_root):
        response = ask(
            "How should audiagentic activate provider harnesses in this project?",
            description=(
                "auto = enable anything detected on PATH; "
                "allowlist = choose which providers up front; "
                "prompt = ask me whenever something new is detected"
            ),
            choices=("auto", "allowlist", "prompt"),
            default_choice="auto",
        )
        mode = response.choice if response.status == ResponseStatus.ANSWERED else "auto"
        if mode not in ("auto", "allowlist", "prompt"):
            mode = "auto"
        set_reconciliation_policy(project_root, mode=mode)

    policy = get_reconciliation_policy(project_root)
    mode = policy.get("mode", "auto")
    if mode not in ("allowlist", "prompt"):
        return

    decided = set(policy.get("decided-providers", []))
    allowed = set(policy.get("allowed-providers", []))
    changed = False

    for provider_id, descriptor in _eligible_provider_descriptors():
        if provider_id in decided:
            continue
        probe = probe_provider_cli(descriptor)
        if not (probe and probe.get("available")):
            continue
        response = ask(f"Enable {provider_id}?", choices=("yes", "no"), default_choice="no")
        if response.status != ResponseStatus.ANSWERED:
            continue
        decided.add(provider_id)
        changed = True
        if response.choice == "yes":
            allowed.add(provider_id)
            # Persist the allowlist before enabling — reconcile_provider's own
            # policy check (ON02) reads it back and must see this provider as
            # allowed, not skip it as "not yet decided".
            set_reconciliation_policy(
                project_root,
                mode=mode,
                allowed_providers=sorted(allowed),
                decided_providers=sorted(decided),
            )
            try:
                reconcile_provider(provider_id, project_root=project_root)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to enable %s immediately after allowlist decision",
                    provider_id,
                    exc_info=True,
                )

    if changed:
        set_reconciliation_policy(
            project_root,
            mode=mode,
            allowed_providers=sorted(allowed),
            decided_providers=sorted(decided),
        )


def reconcile_all(project_root: Path) -> None:
    """Generic post-install hook — reconciles all providers.

    Called from the component lifecycle as a background thread target.
    The first reconciliation must wait until the operator has selected a
    reconciliation policy.  Otherwise the implicit ``auto`` default would
    enable every detected CLI during component installation, before the
    first-run provider selection flow can preserve the operator's choices.
    Silently ignores errors so the component install never fails due to
    provider probe failures.
    """
    from audiagentic.foundation.components.registry import is_installed

    from .config.provider_config import is_reconciliation_policy_configured

    # Guard: component may have been uninstalled before background thread runs.
    if not is_installed("providers", project_root):
        return
    if not is_reconciliation_policy_configured(project_root):
        logger.info("Deferring provider reconciliation until first-run policy is selected")
        return
    try:
        reconcile_all_providers(project_root=project_root)
    except Exception:  # noqa: BLE001
        logger.warning("Background provider reconcile failed", exc_info=True)
