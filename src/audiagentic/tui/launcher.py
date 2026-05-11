"""audiagentic — global entry point for the AUDiaGentic TUI.

Usage
-----
  audiagentic install [--target PATH]   Install Pi TUI (once per machine / shared folder)
  audiagentic [PI_ARGS...]              Launch Pi TUI from the current project directory
  audiagentic --project PATH [PI_ARGS]  Launch with an explicit project root
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audiagentic.provisioning.harness.pi.install import install_to
from audiagentic.provisioning.harness.pi.runner import (
    build_global_context,
    cleanup_rig,
    env_flag,
    run_pi,
)
from audiagentic.tui.global_runtime import global_pi_runtime


def _cmd_install(target: Path) -> int:
    print(f"Installing AUDiaGentic TUI into {target}")
    rc = install_to(target)
    if rc == 0:
        print("\nInstall complete. Run 'audiagentic' from any project directory.")
        if target != global_pi_runtime():
            print(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.")
    return rc


def _cmd_launch(project_root: Path, pi_args: list[str]) -> int:
    if not project_root.exists():
        print(f"Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    pi_runtime = global_pi_runtime()

    if not (pi_runtime / "node" / "node_modules" / ".bin").exists():
        print("Pi TUI not installed. Run: audiagentic install", file=sys.stderr)
        return 1

    enable_mcp = env_flag("AUDIAGENTIC_PI_ENABLE_MCP")
    ctx = build_global_context(
        project_root=project_root,
        pi_runtime=pi_runtime,
        enable_mcp=enable_mcp,
    )
    try:
        return run_pi(ctx, pi_args, smoke=False)
    finally:
        cleanup_rig(ctx.rig_pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audiagentic",
        description="AUDiaGentic TUI",
        add_help=True,
    )
    parser.add_argument(
        "--project",
        metavar="PATH",
        default=None,
        help="Project root directory (default: current working directory)",
    )

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install Pi TUI globally")
    install_parser.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Install location (default: ~/.audiagentic/pi, override with AUDIAGENTIC_HOME)",
    )

    # parse_known_args so remaining args pass through to Pi
    args, remaining = parser.parse_known_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_pi_runtime()
        return _cmd_install(target)

    return _cmd_launch(project_root, remaining)


if __name__ == "__main__":
    raise SystemExit(main())
