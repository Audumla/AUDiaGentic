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
  audiagentic release-bootstrap [--project PATH] [--release-id ID]
  audiagentic [ARGS...]                            Launch agent from current project directory
  audiagentic --project PATH [ARGS]                Launch with explicit project root
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from audiagentic.commands.component import _cmd_component
from audiagentic.commands.launch import _cmd_launch
from audiagentic.commands.provider_prompt import _try_provider_prompt
from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.runtime.harness import (
    install_to,
)
from audiagentic.runtime.home import global_harness_runtime

logger = logging.getLogger(__name__)


def _cmd_install(target: Path, project_root: Path) -> int:
    print(f"Installing AUDiaGentic harness into {target}", flush=True)
    rc = install_to(target, project_root=project_root)
    if rc == 0:
        # Auto-install harness components
        try:
            from audiagentic.foundation.components.loader import register_all_components
            from audiagentic.runtime.lifecycle.components import install_component
            register_all_components()
            install_component(COMPONENT_SESSION, project_root)
        except Exception:
            logger.warning("Failed to auto-install session component", exc_info=True)
        print("\nInstall complete. Run 'audiagentic' from any project directory.", flush=True)
        if target != global_harness_runtime():
            print(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.", flush=True)
    return rc


def _cmd_update() -> int:
    from audiagentic.runtime.update.prompt import run_update_now
    return run_update_now()


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
    parser.add_argument(
        "--prompt", "-p",
        metavar="TEXT",
        default=None,
        help="Run a single prompt, print the result, then exit",
    )
    parser.add_argument(
        "--stream", "-s",
        action="store_true",
        default=False,
        help="Show verbose startup output",
    )
    parser.add_argument(
        "--mode",
        choices=["text", "json"],
        default=None,
        help="Agent output mode when using --prompt (default: text)",
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

    subparsers.add_parser("update", help="Check for a new audiagentic version and update")

    rb_parser = subparsers.add_parser("release-bootstrap", help="Bootstrap release workflow for a project")
    rb_parser.add_argument("--project-root", metavar="PATH", help="Project root directory")
    rb_parser.add_argument("--release-id", default="rel_0001", metavar="ID")

    binaries_parser = subparsers.add_parser("update-binaries", help="Update llama-server binaries to latest release")

    subparsers.add_parser("refresh", help="Regenerate agent config (mcp.json, SYSTEM.md) from current component state")

    args, remaining = parser.parse_known_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    import atexit

    from audiagentic.foundation.logging import bootstrap as _log_bootstrap
    _log_bootstrap("harness", project_root=project_root)
    logger.info("audiagentic started", extra={"project_root": str(project_root), "command": args.command})

    def _log_exit() -> None:
        logger.info("audiagentic exit", extra={"project_root": str(project_root), "command": args.command})

    atexit.register(_log_exit)

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_harness_runtime()
        return _cmd_install(target, project_root=project_root)

    if args.command == "component":
        return _cmd_component(args, project_root)

    if args.command == "update":
        return _cmd_update()

    if args.command == "release-bootstrap":
        from audiagentic.components.optional.ledger import ledger_bootstrap as release_bootstrap
        bootstrap_root = Path(args.project_root).resolve() if args.project_root else project_root
        result = release_bootstrap.bootstrap_ledger(bootstrap_root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "update-binaries":
        from audiagentic.runtime.rig.embedded.binaries import update_binaries
        harness = global_harness_runtime()
        update_binaries(runtime_dir=harness)
        return 0

    if args.command == "refresh":
        from audiagentic.runtime.harness import (
            build_runtime_sync,
            refresh_harness_config_if_installed,
        )
        refreshed = refresh_harness_config_if_installed(project_root, reason="manual-refresh")
        if not refreshed:
            print("Harness not installed. Run: audiagentic install", file=sys.stderr)
            return 1
        print(json.dumps({
            "ok": True,
            "refreshed": True,
            "sync": build_runtime_sync(reason="manual-refresh"),
        }, indent=2))
        return 0

    from audiagentic.runtime.harness import RunnerParams
    params = RunnerParams(
        prompt=args.prompt,
        mode=args.mode,
        verbose=args.stream,
    )

    direct_provider_rc = _try_provider_prompt(args.prompt, project_root)
    if direct_provider_rc is not None:
        return direct_provider_rc

    return _cmd_launch(project_root, remaining, params)

if __name__ == "__main__":
    raise SystemExit(main())
