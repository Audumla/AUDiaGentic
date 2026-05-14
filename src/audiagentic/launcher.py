"""audiagentic — entry point for the AUDiaGentic harness.

Usage
-----
  audiagentic install [--target PATH]   Install harness (once per machine / shared folder)
  audiagentic [ARGS...]                 Launch from the current project directory
  audiagentic --project PATH [ARGS]     Launch with an explicit project root
"""

from __future__ import annotations

import argparse
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

    args, remaining = parser.parse_known_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_harness_runtime()
        return _cmd_install(target, project_root=project_root)

    return _cmd_launch(project_root, remaining)


if __name__ == "__main__":
    raise SystemExit(main())
