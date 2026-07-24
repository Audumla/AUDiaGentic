"""Opencode harness runner.

Uses the same embedded rig as the pi harness — same model profiles, same
endpoint resolution, same shutdown management. The actual CLI invocation
(binary, flags, env) is provider-owned
(components/providers/adapters/opencode/interactive.py, HA03) — this module
only orchestrates the generic launch lifecycle: MCP surface prep, logging,
startup info, and smoke verification.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.runtime.harness.config import env_flag as env_flag
from audiagentic.runtime.harness.context import AgentContext
from audiagentic.runtime.harness.run_common import (
    build_base_run_env,
    make_log_path,
    print_startup_info,
    run_supervised,
    write_run_started,
)
from audiagentic.runtime.harness.run_common import (
    build_global_context as _build_global_context,
)

logger = logging.getLogger(__name__)


def _prepare_mcp_surface(ctx: AgentContext):
    """Compute WHAT AUDiaGentic servers belong in this launch (this module's
    job) and ask the opencode provider adapter HOW to deliver them (its job) —
    routed through the sanctioned providers_api boundary, never an adapter
    import directly (architecture §1)."""
    from audiagentic.components.providers import providers_api
    if ctx.prepared_mcp_surface is not None:
        return ctx.prepared_mcp_surface
    ctx.prepared_mcp_surface = providers_api.prepare_projected_provider_mcp_surface(
        ctx.project_root,
        provider_id="opencode",
        runtime_root=ctx.launch_runtime_root,
        require_exact_isolation=True,
    )
    return ctx.prepared_mcp_surface


def build_global_context(
    *,
    project_root: Path,
    agent_runtime: Path,
    enable_mcp: bool,
) -> AgentContext:
    return _build_global_context(
        "opencode", project_root=project_root, agent_runtime=agent_runtime, enable_mcp=enable_mcp
    )


def translate_agent_args(params) -> list[str]:
    """Translate RunnerParams to opencode CLI flags.

    Delegates to the provider-owned translation
    (components/providers/adapters/opencode/interactive.py) — runtime only
    forwards the call (HA03).
    """
    from audiagentic.components.providers.adapters.opencode.interactive import translate_runner_args

    return translate_runner_args(params)


def run_agent(ctx: AgentContext, agent_args: list[str], *, smoke: bool) -> int:
    from audiagentic.components.providers import providers_api
    from audiagentic.runtime.rig.http import require_models_endpoint

    mcp_surface = _prepare_mcp_surface(ctx) if ctx.enable_mcp else None
    launch = providers_api.prepare_interactive_provider_launch(
        ctx.project_root,
        provider_id="opencode",
        provider=ctx.provider,
        model=ctx.model,
        agent_runtime=ctx.agent_runtime,
        mcp_surface=mcp_surface,
        smoke=smoke,
    )
    env = {**build_base_run_env(ctx), **launch.environment}
    mode = "smoke" if smoke else "run"
    log_path = make_log_path(ctx, mode)

    if smoke:
        print_message(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        require_models_endpoint(ctx.endpoint, timeout=15)
        print_message(f"Checking opencode CLI: {launch.executable}")
        result = subprocess.run(
            [launch.executable, "--version"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            from audiagentic.foundation.contracts.errors import make_error

            raise make_error(
                prefix="EXT",
                component="OCINST",
                number=4,
                kind="opencode-harness",
                message=f"opencode --version failed: {result.stderr.strip()}",
                details={"returncode": result.returncode},
            )
        version = (result.stdout + result.stderr).strip().split("\n")[0]
        print_message(f"opencode: {version}")
        log_path.write_text(f"smoke ok\nopencode: {version}\n", encoding="utf-8")
        return 0

    print_startup_info(ctx, log_path, title="AUDiaGentic (opencode)")

    cmd = [launch.executable, *launch.args] + agent_args

    # Rig shutdown is owned exclusively by the refcounted client registry
    # (shutdown_rig_if_last in commands/launch.py). Killing rig_pid here would
    # destroy a rig other harnesses may still be attached to — rig_pid marks
    # the starter, not the last user (PR04).
    write_run_started(log_path, ctx, agent_args)
    return run_supervised(cmd, ctx.agent_work, env, log_path)
