"""audiagentic — entry point for the AUDiaGentic harness.

Usage
-----
  audiagentic install [--target PATH]              Install harness (once per machine / shared folder)
  audiagentic uninstall [--target PATH]            Remove harness-owned runtime files
  audiagentic component list [--project PATH]      List all registered components and their status
  audiagentic component install ID [--project PATH]
  audiagentic component uninstall ID [--project PATH] [--remove-configs]
  audiagentic component enable ID [--project PATH]
  audiagentic component disable ID [--project PATH]
  audiagentic component status ID [--project PATH]
  audiagentic release-bootstrap [--project PATH] [--release-id ID]
  audiagentic gateway status                       Query gateway service state (SH10)
  audiagentic gateway drain                        Begin graceful drain (SH10)
  audiagentic gateway resume                       Cancel draining; resume running (SH10)
  audiagentic gateway stop [--force]               Request operator stop (SH10)
  audiagentic gateway recover [--confirm] [--reason TEXT]  Recover dead owner, record-only (SH10)
  audiagentic [ARGS...]                            Launch agent from current project directory
  audiagentic --project PATH [ARGS]                Launch with explicit project root
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

from audiagentic.commands.component import _cmd_component
from audiagentic.commands.gateway import (
    cmd_gateway,
    cmd_gateway_drain,
    cmd_gateway_recover,
    cmd_gateway_resume,
    cmd_gateway_status,
    cmd_gateway_stop,
)
from audiagentic.commands.install import cmd_install
from audiagentic.commands.job_control import cmd_job_control
from audiagentic.commands.launch import _cmd_launch
from audiagentic.commands.mcp import cmd_mcp
from audiagentic.commands.provider_prompt import _try_provider_prompt
from audiagentic.commands.refresh import cmd_refresh
from audiagentic.commands.release_bootstrap import cmd_release_bootstrap
from audiagentic.commands.session_input import cmd_session_input
from audiagentic.commands.uninstall import cmd_uninstall
from audiagentic.commands.update import cmd_update
from audiagentic.foundation.cli_io import print_error
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.home import global_harness_runtime

logger = logging.getLogger(__name__)


def _cmd_update_binaries(args: argparse.Namespace, project_root: Path) -> int:
    del args, project_root
    from audiagentic.runtime.rig.embedded.binaries import update_binaries
    harness = global_harness_runtime()
    update_binaries(runtime_dir=harness)
    return 0


# SH10 lifecycle command aliases — keyed by gateway sub-command name.
_GATEWAY_LIFECYCLE_HANDLERS: dict[str, Callable] = {
    "status": cmd_gateway_status,
    "drain": cmd_gateway_drain,
    "resume": cmd_gateway_resume,
    "stop": cmd_gateway_stop,
    "recover": cmd_gateway_recover,
}

_COMMAND_HANDLERS: dict[str, Callable] = {
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "component": _cmd_component,
    "gateway": cmd_gateway,  # legacy: only 'serve' (argparse dispatch)
    "update": cmd_update,
    "mcp": cmd_mcp,
    "job-control": cmd_job_control,
    "session-input": cmd_session_input,
    "release-bootstrap": cmd_release_bootstrap,
    "update-binaries": _cmd_update_binaries,
    "refresh": cmd_refresh,
}


def _main(argv: list[str] | None = None) -> int:
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
    parser.add_argument(
        "--component-profile",
        metavar="NAME",
        default=None,
        help="Component configuration profile name (env: AUDIAGENTIC_COMPONENT_PROFILE)",
    )

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install harness globally")
    install_parser.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Install location (default: ~/.audiagentic/harness, override with AUDIAGENTIC_HOME)",
    )

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove installed harness files")
    uninstall_parser.add_argument(
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

    gateway_parser = subparsers.add_parser("gateway", help="Manage the local agent gateway")
    gateway_sub = gateway_parser.add_subparsers(dest="gateway_cmd", required=True)
    gateway_serve = gateway_sub.add_parser("serve", help="Run the standalone local gateway")
    gateway_serve.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    gateway_serve.add_argument("--port", type=int, default=0)
    gateway_serve.add_argument("--token-file", metavar="PATH")

    # SH10 lifecycle sub-commands (no extra flags except where noted)
    gateway_sub.add_parser("status", help="Query gateway service state")
    gateway_sub.add_parser("drain", help="Begin graceful drain")
    gateway_sub.add_parser("resume", help="Cancel draining; resume running")
    gw_stop = gateway_sub.add_parser("stop", help="Request operator stop")
    gw_stop.add_argument("--force", action="store_true", default=False, help="Force stop even if busy")
    gw_recover = gateway_sub.add_parser("recover", help="Recover dead/unprovable owner (record-only)")
    gw_recover.add_argument("--confirm", action="store_true", default=False, help="Confirm mutation of durable record")
    gw_recover.add_argument("--reason", metavar="TEXT", default=None, help="Reason for recovery")

    subparsers.add_parser("update", help="Check for a new audiagentic version and update")

    job_control_parser = subparsers.add_parser("job-control", help="Request job control action")
    job_control_parser.add_argument("--project-root", metavar="PATH")
    job_control_parser.add_argument("--job-id", required=True)
    job_control_parser.add_argument("--action", required=True, choices=["cancel", "stop", "kill"])
    job_control_parser.add_argument("--requested-by", required=True)
    job_control_parser.add_argument("--reason", required=True)

    session_input_parser = subparsers.add_parser("session-input", help="Record live session input")
    session_input_parser.add_argument("--project-root", metavar="PATH")
    session_input_parser.add_argument("--job-id", required=True)
    session_input_parser.add_argument("--prompt-id")
    session_input_parser.add_argument("--provider-id")
    session_input_parser.add_argument("--surface", required=True)
    session_input_parser.add_argument("--stage", required=True)
    session_input_parser.add_argument("--event-kind", default="user-input")
    session_input_parser.add_argument("--message", required=True)

    rb_parser = subparsers.add_parser("release-bootstrap", help="Bootstrap release workflow for a project")
    rb_parser.add_argument("--project-root", metavar="PATH", help="Project root directory")
    rb_parser.add_argument("--release-id", default="rel_0001", metavar="ID")

    subparsers.add_parser("update-binaries", help="Update llama-server binaries to latest release")

    subparsers.add_parser("refresh", help="Regenerate provider MCP configs (.mcp.json, opencode, …) and agent config from current component state")

    mcp_parser = subparsers.add_parser("mcp", help="Run a component MCP server module over stdio")
    mcp_parser.add_argument("module", metavar="MODULE")
    mcp_parser.add_argument("module_args", nargs=argparse.REMAINDER)

    args, remaining = parser.parse_known_args(argv)

    # Registered commands own a closed argument contract. Unknown tokens must
    # not leak through to handlers or be mistaken for harness passthrough args.
    # No-command invocation intentionally retains passthrough for provider CLIs.
    if args.command is not None and remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    # Propagate --component-profile and --project to env so loader and other
    # modules pick them up (AUDIAGENTIC_REPO_ROOT drives profile resolution,
    # MCP server env forwarding, logging discovery — closes CP13/RV128).
    if args.component_profile:
        import os

        os.environ["AUDIAGENTIC_COMPONENT_PROFILE"] = args.component_profile

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.project:
        import os

        os.environ["AUDIAGENTIC_REPO_ROOT"] = str(project_root)

    import atexit

    from audiagentic.foundation.logging import bootstrap as _log_bootstrap
    _log_bootstrap("harness", project_root=project_root)
    from audiagentic.foundation.interaction import CliBackend, set_backend

    set_backend(CliBackend())

    logger.info("audiagentic started", extra={"project_root": str(project_root), "command": args.command})

    def _log_exit() -> None:
        handlers = list(logging.getLogger().handlers) + list(logger.handlers)
        if any(getattr(getattr(handler, "stream", None), "closed", False) for handler in handlers):
            return
        logger.info("audiagentic exit", extra={"project_root": str(project_root), "command": args.command})

    atexit.register(_log_exit)

    # Dispatch to command handler via registry
    # SH10: gateway lifecycle sub-commands dispatch through a separate
    # registry keyed by the gateway_cmd value (avoids argparse collision).
    if args.command == "gateway" and args.gateway_cmd in _GATEWAY_LIFECYCLE_HANDLERS:
        return _GATEWAY_LIFECYCLE_HANDLERS[args.gateway_cmd](args, project_root)

    # Dispatch to command handler via registry
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler:
        return handler(args, project_root)

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


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except AudiaGenticError as exc:
        print_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
