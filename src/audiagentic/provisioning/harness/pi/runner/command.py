from __future__ import annotations

import os
from pathlib import Path

from .context import AgentContext


def build_agent_command(ctx: AgentContext, *, smoke: bool) -> list[str]:
    cfg = ctx.harness_cfg
    tools_cfg = cfg.get("tools", {})
    ext_cfg = cfg.get("extensions", {})
    sandbox_cfg = cfg.get("sandbox", {})
    lockdown_cfg = cfg.get("lockdown", {})

    command = [str(ctx.agent_bin)]
    command.extend(["--provider", ctx.provider, "--model", ctx.model])

    if smoke:
        command.extend([
            "--no-session", "--no-tools", "--no-context-files",
            "--no-skills", "--no-prompt-templates", "--no-themes",
            "--thinking", "off",
            "--system-prompt", "Return only the exact requested string. No markdown. No explanation.",
            "-p", "Return only this exact ASCII string, no punctuation, no markdown: audiagentic-agent-local-ok",
        ])
    else:
        if tools_cfg.get("no_all", False):
            command.append("--no-tools")
        elif tools_cfg.get("no_builtin", False):
            command.append("--no-builtin-tools")
        elif tools_cfg.get("allow") is not None:
            command.extend(["--tools", ",".join(tools_cfg["allow"])])

        for ext_path in ext_cfg.get("load", []):
            command.extend(["-e", str(ext_path)])

        custom_header = cfg.get("ui", {}).get("custom_header_extension")
        if custom_header:
            command.extend(["-e", str(custom_header)])

        if sandbox_cfg.get("enabled"):
            sandbox_path = sandbox_cfg.get("config_path")
            if sandbox_path:
                command.extend(["--sandbox-config", str(sandbox_path)])

        if lockdown_cfg.get("no_skills", True):
            command.append("--no-skills")
        if lockdown_cfg.get("no_prompt_templates", True):
            command.append("--no-prompt-templates")
        if lockdown_cfg.get("no_context_files", True):
            command.append("--no-context-files")

        for flag in cfg.get("extra_flags", []):
            command.append(flag)

    if not smoke:
        command.append("--no-extensions")
        command.extend(["--extension", str(ctx.agent_dir / "extensions" / "footer.ts")])
        for ext in ext_cfg.get("load", []):
            command.extend(["--extension", str(ext)])

    if ctx.enable_mcp:
        command.extend([
            "--extension", str(ctx.agent_runtime / "cli" / "node_modules" / "pi-mcp-adapter"),
            "--mcp-config", str(ctx.agent_dir / "mcp.json"),
        ])

    return command


def _build_run_env(ctx: AgentContext) -> dict[str, str]:
    import os
    env = os.environ.copy()
    env["HOME"] = str(ctx.agent_home)
    env["PI_CODING_AGENT_DIR"] = str(ctx.agent_dir)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(ctx.project_root / ".audiagentic" / "sessions")
    env["AUDIAGENTIC_REPO_ROOT"] = str(ctx.project_root)
    env["AUDIAGENTIC_AG_BASE_URL"] = ctx.endpoint
    env["AUDIAGENTIC_AG_MODEL"] = ctx.model
    env["AUDIAGENTIC_RIG_TYPE"] = "embedded" if ctx.rig_pid is not None else "external"
    env["AUDIAGENTIC_RIG_PROFILE"] = ctx.profile_name
    return env
