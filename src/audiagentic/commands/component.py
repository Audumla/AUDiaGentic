from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _cmd_component(args: argparse.Namespace, project_root: Path) -> int:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        get_descriptor,
        is_enabled,
        is_installed,
    )
    from audiagentic.runtime.harness import (
        refresh_materialized_agent_config,
        request_runtime_reload,
    )
    from audiagentic.runtime.home import global_harness_runtime
    from audiagentic.runtime.lifecycle.components import (
        disable_component,
        enable_component,
        install_component,
        uninstall_component,
    )

    register_all_components()

    def _refresh_harness_config(component_id: str | None = None, *, reason: str) -> None:
        harness_runtime = global_harness_runtime()
        agent_bin = harness_runtime / "cli" / "node_modules" / ".bin"
        if not agent_bin.exists():
            return
        try:
            refresh_materialized_agent_config(harness_runtime, project_root=project_root)
        except Exception:
            logger.warning("Failed to refresh agent config for %s", component_id, exc_info=True)
        try:
            desc = get_descriptor(component_id) if component_id else None
            has_mcp = bool(desc and (desc.mcp_servers or desc.external_mcp_servers))
            request_runtime_reload(project_root, reason=reason, component_id=component_id, has_mcp_servers=has_mcp)
        except Exception:
            logger.warning("Failed to request runtime reload for %s", component_id, exc_info=True)

    sub = args.component_cmd

    if sub == "list":
        rows = []
        for cid, desc in sorted(all_descriptors().items()):
            installed = is_installed(cid, project_root)
            enabled = is_enabled(cid, project_root) if installed else None
            state = "installed" if installed else "not-installed"
            if installed and not enabled:
                state = "disabled"
            row = {
                "component_id": cid,
                "display_name": desc.display_name,
                "installed": installed,
                "enabled": enabled,
                "state": state,
                "scope": desc.scope,
            }
            if desc.scope == "project" and hasattr(desc, "cli_probe") and desc.cli_probe:
                from audiagentic.components.optional.providers.descriptors.registry import (
                    get_descriptor as _prov_get,
                )
                prov_desc = _prov_get(cid)
                if prov_desc and prov_desc.cli_probe:
                    row["cli_available"] = shutil.which(prov_desc.cli_probe[0]) is not None
            rows.append(row)
        print(json.dumps(rows, indent=2))
        return 0

    component_id: str = args.component_id

    if get_descriptor(component_id) is None:
        print(json.dumps({"ok": False, "error": f"unknown component: {component_id}"}), file=sys.stderr)
        return 1

    if sub == "status":
        installed = is_installed(component_id, project_root)
        result = {
            "component_id": component_id,
            "installed": installed,
            "enabled": is_enabled(component_id, project_root) if installed else None,
        }
        print(json.dumps(result, indent=2))
        return 0

    if sub == "install":
        result = install_component(component_id, project_root)
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-installed")
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1

    if sub == "uninstall":
        result = uninstall_component(
            component_id, project_root, remove_configs=getattr(args, "remove_configs", False)
        )
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-uninstalled")
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1

    if sub == "enable":
        result = enable_component(component_id, project_root)
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-enabled")
        print(json.dumps(result, indent=2))
        return 0

    if sub == "disable":
        result = disable_component(component_id, project_root)
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-disabled")
        print(json.dumps(result, indent=2))
        return 0

    return 1
