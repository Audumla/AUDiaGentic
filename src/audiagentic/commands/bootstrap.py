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


def cmd_config_sync(args: argparse.Namespace, project_root: Path) -> int:
    """Explicitly rebuild generated config; component lifecycle does this normally."""
    del args
    target = global_harness_runtime()
    try:
        # Provider-native MCP files are generated independently of the active
        # harness.  Refresh them first so renamed/removed server modules are
        # repaired everywhere, not only in the harness selected below.
        from audiagentic.components.providers.services.mcp.mcp_sync import (
            sync_all_provider_mcp_servers,
        )

        sync_all_provider_mcp_servers(project_root)
        refresh_materialized_agent_config(target, project_root=project_root)
        request_runtime_reload(project_root, reason="manual-refresh")
    except Exception as exc:  # noqa: BLE001
        print_json({"ok": False, "error": str(exc)})
        return 1
    print_json({"ok": True, "runtime": str(target), "project_root": str(project_root)})
    return 0
