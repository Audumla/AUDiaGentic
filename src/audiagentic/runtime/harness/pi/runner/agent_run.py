from __future__ import annotations

import logging
import os
import subprocess
import sys

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.harness.context import AgentContext, require_smoke_timeout
from audiagentic.runtime.harness.run_common import (
    make_log_path,
    print_startup_info,
    run_supervised,
    write_run_started,
)
from audiagentic.runtime.rig.http import require_models_endpoint

logger = logging.getLogger(__name__)


def check_endpoint(ctx: AgentContext) -> None:
    require_models_endpoint(ctx.endpoint, timeout=15)


def direct_mcp_smoke(ctx: AgentContext, env: dict[str, str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "audiagentic.components.session.session_mcp", "--readonly", "--smoke-only"],
        cwd=ctx.project_root,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise make_error(
            prefix="EXT",
            component="PIRUN",
            number=1,
            kind="pi-harness",
            message=f"Direct MCP smoke failed with exit code {completed.returncode}",
            details={"returncode": completed.returncode},
        )


def run_agent(ctx: AgentContext, agent_args: list[str], *, smoke: bool) -> int:
    if not ctx.agent_bin or not ctx.agent_bin.exists():
        raise make_error(
            prefix="RES",
            component="PIRUN",
            number=2,
            kind="pi-harness",
            message="Pi harness not found. Install pi, then run: audiagentic bootstrap",
            details={"path": str(ctx.agent_bin) if ctx.agent_bin else "not set"},
        )

    if not smoke:
        print_message("\033[2J\033[H", flush=False)

    ctx.agent_work.mkdir(parents=True, exist_ok=True)
    (ctx.project_root / ".audiagentic" / "sessions").mkdir(parents=True, exist_ok=True)

    from .command import _build_run_env, build_agent_command

    env = _build_run_env(ctx)

    mode = "smoke" if smoke else "run"
    log_path = make_log_path(ctx, mode)

    if smoke:
        print_message(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        check_endpoint(ctx)
        if ctx.enable_mcp:
            print_message("Checking direct MCP smoke")
            direct_mcp_smoke(ctx, env)
        else:
            print_message("MCP disabled")
        print_message(f"Writing AudiaGentic smoke log: {log_path}")
    else:
        check_endpoint(ctx)
        tools_cfg = ctx.harness_cfg.get("tools", {})
        if tools_cfg.get("no_all"):
            tools_line = "  Tools:    none (all disabled)"
        elif tools_cfg.get("no_builtin"):
            tools_line = "  Tools:    MCP/extensions only (built-ins disabled)"
        elif tools_cfg.get("allow") is not None:
            tools_line = f"  Tools:    {','.join(tools_cfg['allow'])}"
        else:
            tools_line = "  Tools:    AudiaGentic defaults"
        print_startup_info(ctx, log_path, title="AUDiaGentic", extra_lines=[tools_line])

    command = build_agent_command(ctx, smoke=smoke)

    if smoke:
        smoke_timeout = float(os.environ.get("AUDIAGENTIC_AG_SMOKE_TIMEOUT") or require_smoke_timeout(ctx.harness_cfg))
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                cwd=ctx.agent_work,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                returncode = process.wait(timeout=smoke_timeout)
            except subprocess.TimeoutExpired:
                from audiagentic.foundation.system.process import kill_process_tree

                kill_process_tree(process.pid)
                handle.write(f"\nSmoke timed out after {smoke_timeout:.1f}s\n")
                return 124
        output = log_path.read_text(encoding="utf-8")
        sys.stdout.write(output)
        if returncode == 0 and "audiagentic-agent-local-ok" not in output:
            return 1
        return int(returncode)

    command.extend(agent_args)
    write_run_started(log_path, ctx, agent_args)
    return run_supervised(command, ctx.agent_work, env, log_path)
