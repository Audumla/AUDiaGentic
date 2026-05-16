"""audiagentic — entry point for the AUDiaGentic harness.

Usage
-----
  audiagentic install [--target PATH]              Install harness (once per machine / shared folder)
  audiagentic component list [--project PATH]      List all registered components and their status
  audiagentic component install ID [--project PATH]
  audiagentic component uninstall ID [--project PATH] [--remove-configs]
  audiagentic component enable ID [--project PATH]
  audiagentic component disable ID [--project PATH]
  audiagentic component status ID [--project PATH]
  audiagentic [ARGS...]                            Launch agent from current project directory
  audiagentic --project PATH [ARGS]                Launch with explicit project root
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from audiagentic.provisioning.harness.pi.install import install_to
from audiagentic.provisioning.harness.pi.runner import (
    build_global_context,
    env_flag,
    run_agent,
)
from audiagentic.provisioning.home import global_harness_runtime


def _cmd_install(target: Path, project_root: Path) -> int:
    print(f"Installing AUDiaGentic harness into {target}", flush=True)
    rc = install_to(target, project_root=project_root)
    if rc == 0:
        print("\nInstall complete. Run 'audiagentic' from any project directory.", flush=True)
        if target != global_harness_runtime():
            print(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.", flush=True)
    return rc


def _cmd_component(args: argparse.Namespace, project_root: Path) -> int:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import (
        all_descriptors,
        get_descriptor,
        is_enabled,
        is_installed,
    )
    from audiagentic.runtime.lifecycle.components import (
        disable_component,
        enable_component,
        install_component,
        uninstall_component,
    )

    register_all_components()

    sub = args.component_cmd

    if sub == "list":
        rows = []
        for cid, desc in sorted(all_descriptors().items()):
            installed = is_installed(cid, project_root)
            rows.append({
                "component_id": cid,
                "display_name": desc.display_name,
                "installed": installed,
                "enabled": is_enabled(cid, project_root) if installed else None,
            })
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
        print(json.dumps({"ok": result.get("ok", True), "component_id": component_id}, indent=2))
        return 0 if result.get("ok", True) else 1

    if sub == "uninstall":
        deleted = uninstall_component(
            component_id, project_root, remove_configs=getattr(args, "remove_configs", False)
        )
        print(json.dumps({"ok": True, "component_id": component_id, "deleted": len(deleted)}, indent=2))
        return 0

    if sub == "enable":
        result = enable_component(component_id, project_root)
        print(json.dumps(result, indent=2))
        return 0

    if sub == "disable":
        result = disable_component(component_id, project_root)
        print(json.dumps(result, indent=2))
        return 0

    return 1


def _cmd_launch(project_root: Path, args: list[str]) -> int:
    if not project_root.exists():
        print(f"Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    harness_runtime = global_harness_runtime()

    if not (harness_runtime / "cli" / "node_modules" / ".bin").exists():
        print("Harness not installed. Run: audiagentic install", file=sys.stderr)
        return 1

    enable_mcp = env_flag("AUDIAGENTIC_AG_ENABLE_MCP")
    ctx = build_global_context(
        project_root=project_root,
        agent_runtime=harness_runtime,
        enable_mcp=enable_mcp,
    )

    if ctx.manages_rig:
        from audiagentic.provisioning.rig.registry import register_client, shutdown_rig_if_last

        register_client()

        def _sigterm_handler(sig: int, frame: object) -> None:
            shutdown_rig_if_last()
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _sigterm_handler)
        except (OSError, ValueError):
            pass

        try:
            return run_agent(ctx, args, smoke=False)
        finally:
            shutdown_rig_if_last()
    else:
        return run_agent(ctx, args, smoke=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audiagentic",
        description="AUDiaGentic",
        add_help=True,
    )
    parser.add_argument(
        "--project",
        metavar="PATH",
        default=None,
        help="Project root directory (default: current working directory)",
    )

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install harness globally")
    install_parser.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Install location (default: ~/.audiagentic/harness, override with AUDIAGENTIC_HOME)",
    )

    component_parser = subparsers.add_parser("component", help="Manage installed components")
    component_sub = component_parser.add_subparsers(dest="component_cmd", required=True)

    component_sub.add_parser("list", help="List all components and their status")

    for _sub_name in ("install", "uninstall", "enable", "disable", "status"):
        _p = component_sub.add_parser(_sub_name, help=f"{_sub_name.capitalize()} a component")
        _p.add_argument("component_id", metavar="ID")
        if _sub_name == "uninstall":
            _p.add_argument(
                "--remove-configs",
                action="store_true",
                help="Also delete create-if-missing config files",
            )

    args, remaining = parser.parse_known_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_harness_runtime()
        return _cmd_install(target, project_root=project_root)

    if args.command == "component":
        return _cmd_component(args, project_root)

    return _cmd_launch(project_root, remaining)


if __name__ == "__main__":
    raise SystemExit(main())
