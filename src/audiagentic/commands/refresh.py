"""Refresh command implementation."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_json
from audiagentic.runtime.harness import (
    build_runtime_sync,
    refresh_harness_config_if_installed,
)


def _regenerate_provider_configs(project_root: Path) -> dict[str, object]:
    """Regenerate every provider's MCP config from current component state."""
    result: dict[str, object] = {}
    try:
        from audiagentic.components.providers.services.reconcile import (
            reconcile_all_providers,
        )
        reconciled = reconcile_all_providers(project_root=project_root)
        result["providers_reconciled"] = len(reconciled.get("providers", []))
    except Exception as exc:  # noqa: BLE001
        result["providers_error"] = str(exc)
    try:
        from audiagentic.components.coding_lsp.language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
        )
        lsp = sync_generic_lsp_mcp_to_providers(project_root)
        result["lsp_synced"] = lsp.get("synced", [])
    except Exception as exc:  # noqa: BLE001
        result["lsp_error"] = str(exc)
    return result


def cmd_refresh(args: argparse.Namespace, project_root: Path) -> int:
    del args
    provider_configs = _regenerate_provider_configs(project_root)
    refreshed = refresh_harness_config_if_installed(project_root, reason="manual-refresh")
    print_json({
        "ok": True,
        "provider_configs": provider_configs,
        "harness_refreshed": refreshed,
        "sync": build_runtime_sync(reason="manual-refresh") if refreshed else None,
    })
    return 0
