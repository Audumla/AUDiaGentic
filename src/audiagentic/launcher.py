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
import importlib
import logging
import sys
from pathlib import Path

from audiagentic.cli_io import print_error, print_json, print_message
from audiagentic.commands.component import _cmd_component
from audiagentic.commands.launch import _cmd_launch
from audiagentic.commands.provider_prompt import _try_provider_prompt
from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness import (
    install_to,
)
from audiagentic.runtime.home import global_harness_runtime

logger = logging.getLogger(__name__)


def _cmd_install(target: Path, project_root: Path) -> int:
    print_message(f"Installing AUDiaGentic harness into {target}")
    rc = install_to(target, project_root=project_root)
    if not rc:
        # Auto-install harness components
        try:
            from audiagentic.foundation.components.loader import register_all_components
            from audiagentic.runtime.lifecycle.components import install_component
            register_all_components()
            install_component(COMPONENT_SESSION, project_root)
        except Exception:
            logger.warning("Failed to auto-install session component", exc_info=True)
        print_message("\nInstall complete. Run 'audiagentic' from any project directory.")
        if target != global_harness_runtime():
            print_message(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.")
    return rc


def _cmd_update() -> int:
    from audiagentic.runtime.update.prompt import run_update_now
    return run_update_now()


def _cmd_mcp(module_name: str, module_args: list[str]) -> int:
    module = importlib.import_module(module_name)
    main = getattr(module, "main", None)
    if not callable(main):
        raise AudiaGenticError(
            code="CFG-MCP-002",
            kind="mcp",
            message="MCP module does not expose a callable main()",
            details={"module": module_name},
        )
    old_argv = sys.argv
    try:
        sys.argv = [module_name, *module_args]
        result = main()
    finally:
        sys.argv = old_argv
    return result if isinstance(result, int) else 0


def _regenerate_provider_configs(project_root: Path) -> dict[str, object]:
    """Regenerate every provider's MCP config from current component state.

    Chains the two projections that own provider MCP entries so a single refresh
    rewrites them all in managed launcher form (module renames are picked up
    automatically):
      - provider reconcile: component servers (ag-ledger, ag-release-please, …)
        plus external servers (git, github).
      - LSP generic-mcp projection: the language-server bridge (ag-lsp).
    Each is best-effort: a missing/disabled component never fails the refresh.
    """
    result: dict[str, object] = {}
    try:
        from audiagentic.components.providers.services.reconcile import (
            reconcile_all_providers,
        )
        reconciled = reconcile_all_providers(project_root=project_root)
        result["providers_reconciled"] = len(reconciled.get("providers", []))
    except Exception as exc:  # noqa: BLE001
        result["providers_error"] = str(exc)
    try:
        from audiagentic.components.coding_lsp.language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
        )
        lsp = sync_generic_lsp_mcp_to_providers(project_root)
        result["lsp_synced"] = lsp.get("synced", [])
    except Exception as exc:  # noqa: BLE001
        result["lsp_error"] = str(exc)
    return result


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

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    def _resolve_project_root(explicit: str | None) -> Path:
        """Resolve an explicit project root or fall back to the default."""
        return Path(explicit).resolve() if explicit else project_root

    import atexit

    from audiagentic.foundation.logging import bootstrap as _log_bootstrap
    _log_bootstrap("harness", project_root=project_root)

    logger.info("audiagentic started", extra={"project_root": str(project_root), "command": args.command})

    def _log_exit() -> None:
        handlers = list(logging.getLogger().handlers) + list(logger.handlers)
        if any(getattr(getattr(handler, "stream", None), "closed", False) for handler in handlers):
            return
        logger.info("audiagentic exit", extra={"project_root": str(project_root), "command": args.command})

    atexit.register(_log_exit)

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_harness_runtime()
        return _cmd_install(target, project_root=project_root)

    if args.command == "component":
        return _cmd_component(args, project_root)

    if args.command == "update":
        return _cmd_update()

    if args.command == "mcp":
        return _cmd_mcp(args.module, args.module_args or [])

    if args.command == "job-control":
        try:
            from audiagentic.components.agent_jobs.control import (
                build_job_control_request,
                request_job_control,
            )
        except ImportError:
            print_error("agent_jobs component not available")
            return 1

        from audiagentic.runtime.state.jobs_store import read_job_record

        control_root = _resolve_project_root(args.project_root)
        job = read_job_record(control_root, args.job_id)
        payload = build_job_control_request(
            job_id=args.job_id,
            project_id=job["project-id"],
            requested_action=args.action,
            requested_by=args.requested_by,
            reason=args.reason,
        )
        result = request_job_control(control_root, payload)
        print_json(result, sort_keys=True)
        return 0

    if args.command == "session-input":
        from audiagentic.runtime.state.session_input_store import build_and_persist_session_input

        input_root = _resolve_project_root(args.project_root)
        record = build_and_persist_session_input(
            input_root,
            job_id=args.job_id,
            prompt_id=args.prompt_id,
            provider_id=args.provider_id,
            surface=args.surface,
            stage=args.stage,
            event_kind=args.event_kind,
            message=args.message,
        )
        print_json({"status": "recorded", "record": record}, sort_keys=True)
        return 0

    if args.command == "release-bootstrap":
        try:
            from audiagentic.components.ledger.ledger_bootstrap import bootstrap_ledger
        except ImportError:
            print_error("ledger component not available")
            return 1

        bootstrap_root = _resolve_project_root(args.project_root)
        result = bootstrap_ledger(bootstrap_root)
        print_json(result, sort_keys=True)
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
        # Regenerate provider MCP configs (.mcp.json, .opencode/opencode.json, …)
        # from current component state — independent of whether the agent harness
        # is installed.
        provider_configs = _regenerate_provider_configs(project_root)
        refreshed = refresh_harness_config_if_installed(project_root, reason="manual-refresh")
        print_json({
            "ok": True,
            "provider_configs": provider_configs,
            "harness_refreshed": refreshed,
            "sync": build_runtime_sync(reason="manual-refresh") if refreshed else None,
        })
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


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except AudiaGenticError as exc:
        print_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
