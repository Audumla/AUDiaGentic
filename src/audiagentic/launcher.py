"""audiagentic — entry point for the AUDiaGentic harness.

Usage
-----
  audiagentic bootstrap [--target PATH]            Initialize AUDiaGentic runtime and project scaffold
  audiagentic cleanup [--target PATH]              Remove AUDiaGentic-generated runtime files
  audiagentic component list [--project PATH]      List all registered components and their status
  audiagentic component install ID [--project PATH]
  audiagentic component uninstall ID [--project PATH] [--remove-configs]
  audiagentic component enable ID [--project PATH]
  audiagentic component disable ID [--project PATH]
  audiagentic component status ID [--project PATH]
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

from audiagentic.commands.bootstrap import cmd_bootstrap, cmd_cleanup, cmd_config_sync
from audiagentic.commands.component import _cmd_component
from audiagentic.commands.gateway import (
    cmd_gateway,
    cmd_gateway_drain,
    cmd_gateway_recover,
    cmd_gateway_resume,
    cmd_gateway_status,
    cmd_gateway_stop,
)
from audiagentic.commands.internal import cmd_mcp
from audiagentic.commands.launch import _cmd_launch
from audiagentic.commands.update import cmd_update
from audiagentic.commands.workflow import (
    cmd_release_bootstrap,
    cmd_session_input,
    cmd_work_control,
)
from audiagentic.foundation.cli_io import print_error
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


# SH10 lifecycle command aliases — keyed by gateway sub-command name.
_GATEWAY_LIFECYCLE_HANDLERS: dict[str, Callable] = {
    "status": cmd_gateway_status,
    "drain": cmd_gateway_drain,
    "resume": cmd_gateway_resume,
    "stop": cmd_gateway_stop,
    "recover": cmd_gateway_recover,
}

_COMMAND_HANDLERS: dict[str, Callable] = {
    "bootstrap": cmd_bootstrap,
    "cleanup": cmd_cleanup,
    "component": _cmd_component,
    "gateway": cmd_gateway,  # legacy: only 'serve' (argparse dispatch)
    "update": cmd_update,
    "config": cmd_config_sync,
    "session-input": cmd_session_input,
    "work-control": cmd_work_control,
    "release-bootstrap": cmd_release_bootstrap,
    "mcp": cmd_mcp,
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
        "--prompt",
        "-p",
        metavar="TEXT",
        default=None,
        help="Run a single prompt, print the result, then exit",
    )
    parser.add_argument(
        "--stream",
        "-s",
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

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Initialize AUDiaGentic runtime and project scaffold"
    )
    bootstrap_parser.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Runtime location (default: ~/.audiagentic/harness, override with AUDIAGENTIC_HOME)",
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Remove AUDiaGentic-generated runtime files"
    )
    cleanup_parser.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Runtime location (default: ~/.audiagentic/harness, override with AUDIAGENTIC_HOME)",
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
    gw_stop.add_argument(
        "--force", action="store_true", default=False, help="Force stop even if busy"
    )
    gw_recover = gateway_sub.add_parser(
        "recover", help="Recover dead/unprovable owner (record-only)"
    )
    gw_recover.add_argument(
        "--confirm", action="store_true", default=False, help="Confirm mutation of durable record"
    )
    gw_recover.add_argument("--reason", metavar="TEXT", default=None, help="Reason for recovery")

    subparsers.add_parser("update", help="Check for a new audiagentic version and update")

    session_input_parser = subparsers.add_parser("session-input", help="Record live session input")
    session_input_parser.add_argument("--project-root", metavar="PATH")
    session_input_parser.add_argument("--work-id", required=True)
    session_input_parser.add_argument("--event-kind", default="user-input")
    session_input_parser.add_argument("--message", required=True)

    work_control_parser = subparsers.add_parser(
        "work-control", help="Read or cancel canonical Agent Work"
    )
    work_control_parser.add_argument("--project-root", metavar="PATH")
    work_control_parser.add_argument("--work-id", required=True)
    work_control_parser.add_argument("--action", required=True, choices=["status", "cancel"])

    release_parser = subparsers.add_parser(
        "release-bootstrap", help="Bootstrap release workflow for a project"
    )
    release_parser.add_argument("--project-root", metavar="PATH", help="Project root directory")
    release_parser.add_argument("--release-id", default="rel_0001", metavar="ID")

    config_parser = subparsers.add_parser(
        "config", help="Refresh, clean, and synchronize generated configuration"
    )
    config_sub = config_parser.add_subparsers(dest="config_cmd", required=True)
    config_sub.add_parser(
        "refresh",
        help="Refresh AUDiaGentic surfaces and synchronize configured provider configs",
    )
    config_sub.add_parser(
        "sync",
        help="Alias for config refresh",
    )
    config_sub.add_parser(
        "clean",
        help="Prune AUDiaGentic-owned surfaces and remove generated runtime config",
    )

    # Private stdio entrypoint retained for generated MCP configuration.
    mcp_parser = subparsers.add_parser("mcp", help="Internal MCP stdio entrypoint")
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

    if args.command == "config":
        import os

        os.environ["AUDIAGENTIC_QUIET_STATUS"] = "1"

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.project:
        import os

        os.environ["AUDIAGENTIC_REPO_ROOT"] = str(project_root)

    def _harness_status_functions() -> dict[str, Callable]:
        from audiagentic.runtime.harness import (
            build_runtime_sync,
            default_config_path,
            get_harness_type,
            load_active_profile,
            query_rig_server_version,
            refresh_harness_config_if_installed,
            resolve_session_info,
            version_info,
        )
        from audiagentic.runtime.harness.resolution import harness_cli_available

        return {
            "get_harness_type": get_harness_type,
            "harness_cli_available": harness_cli_available,
            "build_runtime_sync": build_runtime_sync,
            "refresh_harness_config_if_installed": refresh_harness_config_if_installed,
            "query_rig_server_version": query_rig_server_version,
            "version_info": version_info,
            "default_config_path": default_config_path,
            "load_active_profile": load_active_profile,
            "resolve_session_info": resolve_session_info,
        }

    # AS59 Stage 1: process startup is composed, not constructed here. The graph
    # builds runtime.application-host and its dependencies from composition.yaml;
    # the host runs the same startup sequence this function used to inline.
    # Shutdown stays on atexit so exit logging behaves as it did before.
    import atexit

    from audiagentic.runtime.bootstrap import APPLICATION_HOST, build_application_graph

    graph = build_application_graph(project_root=project_root)
    atexit.register(graph.shutdown)
    graph.root(APPLICATION_HOST).start(
        project_root=project_root,
        command=args.command,
        harness_status_functions=_harness_status_functions,
    )

    # Dispatch to command handler via registry
    # SH10: gateway lifecycle sub-commands dispatch through a separate
    # registry keyed by the gateway_cmd value (avoids argparse collision).
    if args.command == "gateway" and args.gateway_cmd in _GATEWAY_LIFECYCLE_HANDLERS:
        return _GATEWAY_LIFECYCLE_HANDLERS[args.gateway_cmd](args, project_root)

    # Dispatch to command handler via registry
    command_name = args.command or ""
    handler = _COMMAND_HANDLERS.get(command_name)
    if handler:
        return handler(args, project_root)

    from audiagentic.runtime.harness import RunnerParams

    params = RunnerParams(
        prompt=args.prompt,
        mode=args.mode,
        verbose=args.stream,
    )

    return _cmd_launch(project_root, remaining, params)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except AudiaGenticError as exc:
        print_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
