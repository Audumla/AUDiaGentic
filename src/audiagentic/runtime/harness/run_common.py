from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from audiagentic.cli_io import print_message
from audiagentic.runtime.harness.context import AgentContext


def build_base_run_env(ctx: AgentContext) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["AUDIAGENTIC_REPO_ROOT"] = str(ctx.project_root)
    env["AUDIAGENTIC_AG_BASE_URL"] = ctx.endpoint
    env["AUDIAGENTIC_AG_MODEL"] = ctx.model
    env["AUDIAGENTIC_RIG_TYPE"] = "embedded" if ctx.manages_rig else "external"
    env["AUDIAGENTIC_RIG_PROFILE"] = ctx.profile_name
    env["OPENAI_API_BASE"] = ctx.endpoint
    env["OPENAI_BASE_URL"] = ctx.endpoint
    env["OPENAI_API_KEY"] = "dummy"
    return env


def make_log_path(ctx: AgentContext, mode: str) -> Path:
    ctx.agent_log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ctx.agent_log_dir / f"{mode}-{stamp}.log"


def write_run_started(log_path: Path, ctx: AgentContext, agent_args: list[str]) -> None:
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


def append_run_finished(log_path: Path, returncode: int) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "agent_run_finished", "returncode": int(returncode)}) + "\n")


def print_startup_info(
    ctx: AgentContext,
    log_path: Path,
    *,
    title: str,
    extra_lines: list[str] | None = None,
) -> None:
    ui_cfg = ctx.harness_cfg.get("ui", {})
    banner = ui_cfg.get("startup_banner")
    if banner:
        print_message(banner, flush=str(banner).endswith("\n"))
    if not ui_cfg.get("show_startup_info", True):
        return
    print_message(title)
    print_message(f"  Project:  {ctx.project_root}")
    print_message(f"  Provider: {ctx.provider}")
    print_message(f"  Model:    {ctx.model}")
    print_message(f"  Endpoint: {ctx.endpoint}")
    if ctx.server_version:
        print_message(f"  Server:   {ctx.server_version}")
    print_message(f"  MCP:      {'enabled' if ctx.enable_mcp else 'disabled'}")
    for line in extra_lines or []:
        print_message(line)
    print_message(f"  Log:      {log_path}")
    print_message("")


def run_supervised(command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> int:
    from audiagentic.foundation.system.supervised_process import supervised_run

    returncode = int(supervised_run(command, cwd=cwd, env=env))
    append_run_finished(log_path, returncode)
    return returncode
