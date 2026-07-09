from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from audiagentic.foundation.cli_io import print_error

if TYPE_CHECKING:
    from audiagentic.runtime.harness import RunnerParams

logger = logging.getLogger(__name__)

_RECONCILE_PROVIDERS_ENV = "AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH"


def _status(msg: str) -> None:
    """Print a startup status line to stderr. Set AUDIAGENTIC_STARTUP_STATUS=0 to suppress."""
    if os.environ.get("AUDIAGENTIC_STARTUP_STATUS", "1") != "0":
        print_error(f"[audiagentic] {msg}")


def _provider_reconcile_stamp_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers" / "launch-reconciled"


def _should_reconcile_providers_on_launch(project_root: Path) -> bool:
    setting = os.environ.get(_RECONCILE_PROVIDERS_ENV, "").strip().lower()
    if setting in {"0", "false", "no", "never", "off"}:
        return False
    if setting in {"1", "true", "yes", "always", "on"}:
        return True

    from audiagentic.foundation.features.state import shard_path

    providers_feature_state = shard_path(project_root, "providers")
    return not providers_feature_state.exists() and not _provider_reconcile_stamp_path(project_root).exists()


def _mark_provider_launch_reconciled(project_root: Path) -> None:
    stamp_path = _provider_reconcile_stamp_path(project_root)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text("reconciled\n", encoding="utf-8")


def _cmd_launch(project_root: Path, args: list[str], runner_params: RunnerParams | None = None) -> int:
    if not project_root.exists():
        print_error(f"Project root does not exist: {project_root}")
        return 1

    from audiagentic.foundation.paths.home import global_harness_runtime

    harness_runtime = global_harness_runtime()

    if not (harness_runtime / "cli" / "node_modules" / ".bin").exists():
        print_error("Harness not installed. Run: audiagentic install")
        return 1

    # Check for updates if auto-update is enabled
    _status("checking for updates...")
    try:
        if os.environ.get("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "true").lower() == "true":
            from audiagentic.runtime.update.prompt import maybe_prompt_update
            maybe_prompt_update(project_root)
    except Exception:
        logger.warning("Auto-update check failed", exc_info=True)

    # Sync provider enablement with actual host state on first run only.
    # Subsequent reconciliations are available via the provider MCP server.
    try:
        from audiagentic.components.providers.services.lifecycle import reconcile_all_providers

        if _should_reconcile_providers_on_launch(project_root):
            _status("reconciling providers...")

            def _on_provider(provider_id: str, status: str) -> None:
                if status in ("enabled", "disabled"):
                    _status(f"  {provider_id}: {status}")

            reconcile_all_providers(project_root=project_root, on_provider=_on_provider)
            _mark_provider_launch_reconciled(project_root)
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

    if runner_params:
        args = translate_agent_args(runner_params) + args

    if ctx.manages_rig:
        # Client registration happened inside launch_rig_if_needed, under the
        # rig start lock — registering here (outside the lock) left a window
        # where a departing last client killed the rig we just attached to.
        from audiagentic.runtime.rig.registry import shutdown_rig_if_last

        rig_port = int(str(ctx.endpoint).rsplit(":", 1)[-1].split("/", 1)[0])

        def _sigterm_handler(sig: int, frame: object) -> None:
            shutdown_rig_if_last(rig_port)
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _sigterm_handler)
        except (OSError, ValueError):
            logger.debug("Could not register SIGTERM handler (non-Linux or signal already set)")

        try:
            return run_agent(ctx, args, smoke=False)  # type: ignore[arg-type]
        finally:
            shutdown_rig_if_last(rig_port)
    else:
        return run_agent(ctx, args, smoke=False)  # type: ignore[arg-type]
