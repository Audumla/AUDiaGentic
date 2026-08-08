"""Bootstrap and repair commands for AUDiaGentic-owned state."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json, print_message
from audiagentic.foundation.paths.home import global_harness_runtime
from audiagentic.runtime.harness import (
    cleanup_runtime,
    install_to,
    refresh_materialized_agent_config,
    request_runtime_reload,
)

logger = logging.getLogger(__name__)


def _install_core_components(project_root: Path) -> list[str]:
    """Materialize every mandatory project component; return failed ids.

    These components own project scaffold (configuration, prompts and event-bus
    state).  They are deliberately independent of MCP collection.
    """
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors
    from audiagentic.foundation.lifecycle.components import install_component

    register_all_components()
    failed: list[str] = []
    for component_id, descriptor in all_descriptors().items():
        if not descriptor.core:
            continue
        try:
            result = install_component(component_id, project_root)
            if not result.get("ok"):
                failed.append(component_id)
        except Exception:
            logger.error("Failed to bootstrap core component %s", component_id, exc_info=True)
            failed.append(component_id)
    return failed


def _cmd_bootstrap(target: Path, project_root: Path) -> int:
    print_message(f"Bootstrapping AUDiaGentic into {target}")
    rc = install_to(target, project_root=project_root)
    if rc:
        return rc

    failed = _install_core_components(project_root)
    if failed:
        print_error(f"Failed to bootstrap core components: {', '.join(sorted(failed))}")
        return 1

    print_message("\nBootstrap complete. Run 'audiagentic' from any project directory.")
    if target != global_harness_runtime():
        print_message(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.")
    return 0


def cmd_bootstrap(args: argparse.Namespace, project_root: Path) -> int:
    target = Path(args.target).resolve() if args.target else global_harness_runtime()
    return _cmd_bootstrap(target, project_root)


def cmd_cleanup(args: argparse.Namespace, project_root: Path) -> int:
    del project_root
    target = Path(args.target).resolve() if args.target else global_harness_runtime()
    print_message(f"Removing AUDiaGentic-generated runtime files from {target}")
    return cleanup_runtime(target)


def _surface_results_to_json(results: object) -> list[dict[str, object]]:
    """Serialize generated-surface API results for CLI output."""
    values = results if isinstance(results, list) else [results]
    serialized: list[dict[str, object]] = []
    for value in values:
        converter = getattr(value, "to_mapping", None)
        if callable(converter):
            value = converter()
        serialized.append(dict(value) if isinstance(value, dict) else {"result": str(value)})
    return serialized


def _config_operation(project_root: Path, *, mode: str, clean_runtime: bool) -> int:
    """Run an ownership-aware config operation and report partial failures."""
    target = global_harness_runtime()
    from audiagentic.components.providers import providers_api
    from audiagentic.components.providers.services.mcp.mcp_sync import (
        sync_all_provider_mcp_servers,
    )

    output: dict[str, object] = {
        "ok": True,
        "mode": mode,
        "project_root": str(project_root),
        "runtime": str(target),
        "surfaces": [],
        "provider_configs": [],
        "errors": [],
    }
    try:
        surface_results = _surface_results_to_json(
            providers_api.operate_provider_surfaces(project_root, mode=mode)
        )
        provider_errors = sync_all_provider_mcp_servers(project_root)
        output["surfaces"] = surface_results
        output["provider_configs"] = provider_errors
        if clean_runtime:
            cleanup_runtime(target)
        else:
            refresh_materialized_agent_config(target, project_root=project_root)
        request_runtime_reload(project_root, reason=f"config-{mode}")
    except Exception as exc:  # noqa: BLE001
        output["ok"] = False
        output["errors"] = [str(exc)]
        print_json(output)
        return 1

    surface_errors = [
        result
        for result in surface_results
        if not result.get("ok", False) and result.get("supported", True)
    ]
    if surface_errors or provider_errors:
        output["ok"] = False
        output["errors"] = surface_errors + provider_errors
        print_json(output)
        return 1

    print_json(output)
    return 0


def cmd_config_sync(args: argparse.Namespace, project_root: Path) -> int:
    """Refresh all generated surfaces and configured provider configs."""
    if args.config_cmd == "clean":
        return cmd_config_clean(args, project_root)
    return _config_operation(project_root, mode="apply", clean_runtime=False)


def cmd_config_clean(args: argparse.Namespace, project_root: Path) -> int:
    """Prune owned surfaces, synchronize stale provider entries, and clean runtime."""
    del args
    return _config_operation(project_root, mode="prune", clean_runtime=True)
