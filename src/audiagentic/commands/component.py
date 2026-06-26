from __future__ import annotations

import argparse
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.cli_io import print_json

logger = logging.getLogger(__name__)


def _cmd_component_list(_args: Any, project_root: Path) -> int:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        is_enabled,
        is_installed,
    )

    register_all_components()

    rows = []
    for cid, desc in sorted(all_descriptors().items()):
        installed = is_installed(cid, project_root)
        enabled = is_enabled(cid, project_root) if installed else None
        state = "disabled" if (installed and not enabled) else ("installed" if installed else "not-installed")
        row: dict[str, Any] = {
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


def _cmd_component_status(args: Any, project_root: Path) -> int:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        get_descriptor,
        is_enabled,
        is_installed,
    )

    register_all_components()

    component_id: str = args.component_id

    if get_descriptor(component_id) is None:
        print_json({"ok": False, "error": f"unknown component: {component_id}"})
        return 1

    installed = is_installed(component_id, project_root)
    result = {
        "component_id": component_id,
        "installed": installed,
        "enabled": is_enabled(component_id, project_root) if installed else None,
    }
    print_json(result)
    return 0


_SUBCOMMAND_REGISTRY: dict[str, Callable] = {
    "list": _cmd_component_list,
    "status": _cmd_component_status,
}


def _cmd_component(args: argparse.Namespace, project_root: Path) -> int:
    from audiagentic.components.project import project_api
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import get_descriptor

    register_all_components()

    sub = args.component_cmd

    handler = _SUBCOMMAND_REGISTRY.get(sub)
    if handler:
        return handler(args, project_root)

    component_id: str = args.component_id

    if get_descriptor(component_id) is None:
        print_json({"ok": False, "error": f"unknown component: {component_id}"})
        return 1

    DISPATCH = {
        "install": ("install_component", {}),
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
