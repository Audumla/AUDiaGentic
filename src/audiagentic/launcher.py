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
import os
import re
import shutil
import signal
import sys
from pathlib import Path


def _status(msg: str) -> None:
    """Print a startup status line to stderr. Set AUDIAGENTIC_STARTUP_STATUS=0 to suppress."""
    if os.environ.get("AUDIAGENTIC_STARTUP_STATUS", "1") != "0":
        print(f"[audiagentic] {msg}", file=sys.stderr, flush=True)

from audiagentic.runtime.harness.pi.install import install_to
from audiagentic.runtime.harness.pi.runner import (
    RunnerParams,
    build_global_context,
    env_flag,
    run_agent,
)
from audiagentic.runtime.home import global_harness_runtime


def _cmd_install(target: Path, project_root: Path) -> int:
    print(f"Installing AUDiaGentic harness into {target}", flush=True)
    rc = install_to(target, project_root=project_root)
    if rc == 0:
        # Auto-install harness components
        try:
            from audiagentic.foundation.components.loader import register_all_components
            from audiagentic.runtime.lifecycle.components import install_component
            register_all_components()
            install_component("session", project_root)
        except Exception:
            pass
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
    from audiagentic.runtime.harness.pi.install import (
        refresh_materialized_agent_config,
        request_runtime_reload,
    )
    from audiagentic.runtime.home import global_harness_runtime
    from audiagentic.runtime.lifecycle.components import (
        disable_component,
        enable_component,
        install_component,
        uninstall_component,
    )

    register_all_components()

    def _refresh_harness_config(component_id: str | None = None, *, reason: str) -> None:
        harness_runtime = global_harness_runtime()
        agent_bin = harness_runtime / "cli" / "node_modules" / ".bin"
        if not agent_bin.exists():
            return
        try:
            refresh_materialized_agent_config(harness_runtime, project_root=project_root)
        except Exception:
            pass
        try:
            request_runtime_reload(project_root, reason=reason, component_id=component_id)
        except Exception:
            pass

    sub = args.component_cmd

    if sub == "list":
        rows = []
        for cid, desc in sorted(all_descriptors().items()):
            installed = is_installed(cid, project_root)
            enabled = is_enabled(cid, project_root) if installed else None
            state = "installed" if installed else "not-installed"
            if installed and not enabled:
                state = "disabled"
            row = {
                "component_id": cid,
                "display_name": desc.display_name,
                "installed": installed,
                "enabled": enabled,
                "state": state,
            }
            if desc.scope == "project" and hasattr(desc, "cli_probe") and desc.cli_probe:
                from audiagentic.components.optional.providers.descriptors.registry import (
                    get_descriptor as _prov_get,
                )
                prov_desc = _prov_get(cid)
                if prov_desc and prov_desc.cli_probe:
                    row["cli_available"] = shutil.which(prov_desc.cli_probe[0]) is not None
            rows.append(row)
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
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-installed")
        print(json.dumps({"ok": result.get("ok", True), "component_id": component_id}, indent=2))
        return 0 if result.get("ok", True) else 1

    if sub == "uninstall":
        deleted = uninstall_component(
            component_id, project_root, remove_configs=getattr(args, "remove_configs", False)
        )
        _refresh_harness_config(component_id, reason="component-uninstalled")
        print(json.dumps({"ok": True, "component_id": component_id, "deleted": len(deleted)}, indent=2))
        return 0

    if sub == "enable":
        result = enable_component(component_id, project_root)
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-enabled")
        print(json.dumps(result, indent=2))
        return 0

    if sub == "disable":
        result = disable_component(component_id, project_root)
        if result.get("ok", True):
            _refresh_harness_config(component_id, reason="component-disabled")
        print(json.dumps(result, indent=2))
        return 0

    return 1


def _cmd_update() -> int:
    from audiagentic.runtime.update.prompt import run_update_now
    return run_update_now()


def _try_provider_prompt(prompt: str | None, project_root: Path) -> int | None:
    """Handle unambiguous provider lifecycle prompts directly with live output.

    Pi's MCP adapter does not surface MCP log notifications in non-interactive
    prompt mode, so direct lifecycle prompts need to bypass the agent to provide
    user-visible streaming while still using the provider component backend.
    """
    if not prompt:
        return None

    reconcile_all_match = re.fullmatch(
        r"\s*reconcile\s+(?:all\s+)?(?:providers?|provider\s+clis?)\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    reconcile_one_match = re.fullmatch(
        r"\s*reconcile\s+([a-z0-9_.-]+)(?:\s+(?:provider|provider\s+cli))?\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if reconcile_all_match or reconcile_one_match:
        from audiagentic.components.optional.providers.services.lifecycle import (
            reconcile_all_providers,
            reconcile_provider,
        )

        def _progress(event) -> None:
            message = getattr(event, "message", str(event))
            print(message, flush=True)

        if reconcile_all_match:
            result = reconcile_all_providers(project_root=project_root, on_progress=_progress)
        else:
            result = reconcile_provider(reconcile_one_match.group(1).lower(), project_root=project_root, on_progress=_progress)

        print(json.dumps(result, indent=2), flush=True)
        return 0 if result.get("ok", True) else 1

    match = re.fullmatch(
        r"\s*(install|uninstall|repair)\s+(?:the\s+)?([a-z0-9_.-]+)(?:\s+(?:provider|provider\s+cli))?\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    action = match.group(1).lower()
    provider_id = match.group(2).lower()

    from audiagentic.components.optional.providers.services.lifecycle import (
        install_provider_cli,
        repair_provider_cli,
        uninstall_provider_cli,
    )

    handlers = {
        "install": install_provider_cli,
        "uninstall": uninstall_provider_cli,
        "repair": repair_provider_cli,
    }

    def _progress(event) -> None:
        message = getattr(event, "message", str(event))
        print(f"[{provider_id}] {message}", flush=True)

    result = handlers[action](
        provider_id,
        dry_run=False,
        project_root=project_root,
        on_progress=_progress,
    )
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result.get("status") in {"installed", "uninstalled", "repaired", "skipped"} else 1


def _cmd_launch(project_root: Path, args: list[str], runner_params: RunnerParams | None = None) -> int:
    if not project_root.exists():
        print(f"Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    harness_runtime = global_harness_runtime()

    if not (harness_runtime / "cli" / "node_modules" / ".bin").exists():
        print("Harness not installed. Run: audiagentic install", file=sys.stderr)
        return 1

    # Check for updates if auto-update is enabled
    _status("checking for updates...")
    try:
        if os.environ.get("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "true").lower() == "true":
            from audiagentic.runtime.update.prompt import maybe_prompt_update
            maybe_prompt_update(project_root)
    except Exception:
        pass

    # Sync providers.yaml with actual host state on first run only.
    # Subsequent reconciliations are available via the provider MCP server.
    try:
        from audiagentic.components.optional.providers.services.provider_config import (
            _providers_yaml_path,
        )

        providers_path = _providers_yaml_path(project_root)
        if not providers_path.exists():
            _status("reconciling providers...")
            from audiagentic.components.optional.providers.services.lifecycle import (
                reconcile_all_providers,
            )

            def _on_provider(provider_id: str, status: str) -> None:
                if status in ("enabled", "disabled"):
                    _status(f"  {provider_id}: {status}")

            reconcile_all_providers(project_root=project_root, on_provider=_on_provider)
    except Exception:
        pass

    _status("refreshing agent config...")
    try:
        from audiagentic.runtime.harness.pi.install import refresh_materialized_agent_config

        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
    except Exception:
        pass

    _status("starting agent...")
    enable_mcp = env_flag("AUDIAGENTIC_AG_ENABLE_MCP")
    from audiagentic.runtime.harness.pi.runner import translate_agent_args
    ctx = build_global_context(
        project_root=project_root,
        agent_runtime=harness_runtime,
        enable_mcp=enable_mcp,
    )

    if runner_params is not None:
        args = translate_agent_args(runner_params) + args

    if ctx.manages_rig:
        from audiagentic.runtime.rig.registry import register_client, shutdown_rig_if_last

        register_client()
        rig_port = int(str(ctx.endpoint).rsplit(":", 1)[-1].split("/", 1)[0])

        def _sigterm_handler(sig: int, frame: object) -> None:
            shutdown_rig_if_last(rig_port)
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _sigterm_handler)
        except (OSError, ValueError):
            pass

        try:
            return run_agent(ctx, args, smoke=False)
        finally:
            shutdown_rig_if_last(rig_port)
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

    args, remaining = parser.parse_known_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd()

    if args.command == "install":
        target = Path(args.target).resolve() if args.target else global_harness_runtime()
        return _cmd_install(target, project_root=project_root)

    if args.command == "component":
        return _cmd_component(args, project_root)

    if args.command == "update":
        return _cmd_update()

    if args.command == "release-bootstrap":
        from audiagentic.components.optional.ledger import bootstrap as release_bootstrap
        bootstrap_root = Path(args.project_root).resolve() if args.project_root else project_root
        result = release_bootstrap.bootstrap_release_workflow(bootstrap_root, release_id=args.release_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "update-binaries":
        from audiagentic.runtime.rig.embedded.update_binaries import update_binaries
        harness = global_harness_runtime()
        update_binaries(runtime_dir=harness)
        return 0

    from audiagentic.runtime.harness.pi.runner import RunnerParams
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
