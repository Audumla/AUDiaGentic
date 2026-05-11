"""audiagentic — entry point for the AUDiaGentic harness.

Usage
-----
  audiagentic install [--target PATH]   Install harness (once per machine / shared folder)
  audiagentic [ARGS...]                 Launch from the current project directory
  audiagentic --project PATH [ARGS]     Launch with an explicit project root
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from audiagentic.provisioning.harness.pi.install import install_to
from audiagentic.provisioning.harness.pi.runner import (
    build_global_context,
    cleanup_rig,
    env_flag,
    run_pi,
)


def _audiagentic_home() -> Path:
    custom = os.environ.get("AUDIAGENTIC_HOME")
    return Path(custom) if custom else Path.home() / ".audiagentic"


def global_harness_runtime() -> Path:
    return _audiagentic_home() / "harness"


def _cmd_install(target: Path) -> int:
    print(f"Installing AUDiaGentic harness into {target}")
    rc = install_to(target)
    if rc == 0:
        print("\nInstall complete. Run 'audiagentic' from any project directory.")
        if target != global_harness_runtime():
            print(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.")
    return rc


def _cmd_launch(project_root: Path, args: list[str]) -> int:
    if not project_root.exists():
        print(f"Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    harness_runtime = global_harness_runtime()

    if not (harness_runtime / "node" / "node_modules" / ".bin").exists():
        print("Harness not installed. Run: audiagentic install", file=sys.stderr)
        return 1

    enable_mcp = env_flag("AUDIAGENTIC_PI_ENABLE_MCP")
    ctx = build_global_context(
        project_root=project_root,
        pi_runtime=harness_runtime,
        enable_mcp=enable_mcp,
    )
    try:
        return run_pi(ctx, args, smoke=False)
    finally:
        cleanup_rig(ctx.rig_pid)


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
        return _cmd_install(target)

    return _cmd_launch(project_root, remaining)


if __name__ == "__main__":
    raise SystemExit(main())
