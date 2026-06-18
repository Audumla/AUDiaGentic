from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiagentic.runtime.harness import RunnerParams

logger = logging.getLogger(__name__)


def _status(msg: str) -> None:
    """Print a startup status line to stderr. Set AUDIAGENTIC_STARTUP_STATUS=0 to suppress."""
    if os.environ.get("AUDIAGENTIC_STARTUP_STATUS", "1") != "0":
        print(f"[audiagentic] {msg}", file=sys.stderr, flush=True)


def _cmd_launch(project_root: Path, args: list[str], runner_params: RunnerParams | None = None) -> int:
    if not project_root.exists():
        print(f"Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    from audiagentic.runtime.home import global_harness_runtime

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
        logger.warning("Auto-update check failed", exc_info=True)

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
        logger.warning("Provider reconciliation failed", exc_info=True)

    _status("refreshing agent config...")
    try:
        from audiagentic.runtime.harness import refresh_materialized_agent_config

        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
    except Exception:
        logger.warning("Failed to refresh agent config", exc_info=True)

    _status("starting agent...")
    from audiagentic.runtime.harness import (
        build_global_context,
        env_flag,
        run_agent,
        translate_agent_args,
    )

    enable_mcp = env_flag("AUDIAGENTIC_AG_ENABLE_MCP")
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
