from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from audiagentic.cli_io import print_json

logger = logging.getLogger(__name__)


def _cmd_component(args: argparse.Namespace, project_root: Path) -> int:
    from audiagentic.components.project import project_api
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        get_descriptor,
        is_enabled,
        is_installed,
    )

    register_all_components()

    sub = args.component_cmd

    if sub == "list":
        rows = []
        for cid, desc in sorted(all_descriptors().items()):
            installed = is_installed(cid, project_root)
            enabled = is_enabled(cid, project_root) if installed else None
            state = "disabled" if (installed and not enabled) else ("installed" if installed else "not-installed")
            row = {
                "component_id": cid,
                "display_name": desc.display_name,
                "installed": installed,
                "enabled": enabled,
                "state": state,
                "scope": desc.scope,
            }
            if desc.scope == "project" and (getattr(desc, "cli_probe", None)):
                try:
                    from audiagentic.components.providers.descriptors.registry import (
                        get_descriptor as _get_provider_descriptor,
                    )
                except ImportError:
                    pass
                else:
                    prov_desc = _get_provider_descriptor(cid)
                    if prov_desc and prov_desc.cli_probe:
                        row["cli_available"] = shutil.which(prov_desc.cli_probe[0]) is not None
            rows.append(row)
        print_json(rows)
        return 0

    component_id: str = args.component_id

    if get_descriptor(component_id) is None:
        print_json({"ok": False, "error": f"unknown component: {component_id}"})
        return 1

    if sub == "status":
        installed = is_installed(component_id, project_root)
        result = {
            "component_id": component_id,
            "installed": installed,
            "enabled": is_enabled(component_id, project_root) if installed else None,
        }
        print_json(result)
        return 0

    DISPATCH = {
        "install": ("install_component", {"remove_configs": False}),
        "uninstall": ("uninstall_component", {"remove_configs": getattr(args, "remove_configs", False)}),
        "enable": ("enable_component", {}),
        "disable": ("disable_component", {}),
    }

    if sub in DISPATCH:
        api_method, extra_kwargs = DISPATCH[sub]
        result = getattr(project_api, f"{api_method}")(project_root, component_id, **extra_kwargs)
        print_json(result)
        return 0 if result.get("ok", True) else 1

    return 1
