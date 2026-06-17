from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

from audiagentic.runtime.rig.http import require_models_endpoint

from .context import AgentContext, require_smoke_timeout


def check_endpoint(ctx: AgentContext) -> None:
    require_models_endpoint(ctx.endpoint, timeout=15)


def direct_mcp_smoke(ctx: AgentContext, env: dict[str, str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "audiagentic.components.core.session.session_mcp", "--readonly", "--smoke-only", "--direct-smoke"],
        cwd=ctx.project_root,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_agent(ctx: AgentContext, agent_args: list[str], *, smoke: bool) -> int:
    if not ctx.agent_bin.exists():
        raise SystemExit("AudiaGentic agent not found. Run: audiagentic install")

    if not smoke:
        print("\033[2J\033[H", end="", flush=True)

    ctx.agent_work.mkdir(parents=True, exist_ok=True)
    ctx.agent_log_dir.mkdir(parents=True, exist_ok=True)
    (ctx.project_root / ".audiagentic" / "sessions").mkdir(parents=True, exist_ok=True)

    from .command import _build_run_env, build_agent_command

    env = _build_run_env(ctx)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "smoke" if smoke else "run"
    log_path = ctx.agent_log_dir / f"{mode}-{stamp}.log"

    if smoke:
        print(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        check_endpoint(ctx)
        if ctx.enable_mcp:
            print("Checking direct MCP smoke")
            direct_mcp_smoke(ctx, env)
        else:
            print("MCP disabled")
        print(f"Writing AudiaGentic smoke log: {log_path}")
    else:
        check_endpoint(ctx)
        ui_cfg = ctx.harness_cfg.get("ui", {})
        tools_cfg = ctx.harness_cfg.get("tools", {})

        banner = ui_cfg.get("startup_banner")
        if banner:
            print(banner, end="" if str(banner).endswith("\n") else "\n")

        if ui_cfg.get("show_startup_info", True):
            print("AUDiaGentic")
            print(f"  Project:  {ctx.project_root}")
            print(f"  Provider: {ctx.provider}")
            print(f"  Model:    {ctx.model}")
            print(f"  Endpoint: {ctx.endpoint}")
            if ctx.server_version:
                print(f"  Server:   {ctx.server_version}")
            print(f"  MCP:      {'enabled' if ctx.enable_mcp else 'disabled'}")
            if tools_cfg.get("no_all"):
                print("  Tools:    none (all disabled)")
            elif tools_cfg.get("no_builtin"):
                print("  Tools:    MCP/extensions only (built-ins disabled)")
            elif tools_cfg.get("allow") is not None:
                print(f"  Tools:    {','.join(tools_cfg['allow'])}")
            else:
                print("  Tools:    AudiaGentic defaults")
            print(f"  Log:      {log_path}")
            print()

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
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": "agent_run_started",
                    "project_root": str(ctx.project_root),
                    "provider": ctx.provider,
                    "model": ctx.model,
                    "endpoint": ctx.endpoint,
                    "mcp": ctx.enable_mcp,
                    "args": agent_args,
                },
                indent=2,
            )
            + "\n"
        )

    completed = subprocess.run(command, cwd=ctx.agent_work, env=env, check=False)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "agent_run_finished", "returncode": int(completed.returncode)}) + "\n")
    return int(completed.returncode)
