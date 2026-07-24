"""Pi interactive (TUI) launch builder.

Builds the command/environment for launching the `pi` binary itself for a
human-facing interactive session -- distinct from acp.py's build_acp_launch,
which launches the separate `pi-acp` headless RPC bridge for programmatic
sessions. This is the provider-owned home for what used to live in
runtime/harness/pi/runner/command.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.config import load_layered_config
from audiagentic.foundation.paths.package import PACKAGE_ROOT
from audiagentic.foundation.transports import ProviderLaunch

_PI_CONFIG = PACKAGE_ROOT / "config" / "provisioning" / "harness" / "pi.yaml"

_SMOKE_ARGS: tuple[str, ...] = (
    "--no-session", "--no-tools", "--no-context-files",
    "--no-skills", "--no-prompt-templates", "--no-themes",
    "--thinking", "off",
    "--system-prompt", "Return only the exact requested string. No markdown. No explanation.",
    "-p", "Return only this exact ASCII string, no punctuation, no markdown: audiagentic-agent-local-ok",
)


def resolve_agent_bin(agent_runtime: Path) -> Path:
    del agent_runtime  # signature symmetry only -- the CLI comes from PATH, not a bundled copy
    return Path(require_executable("pi", "pi"))


def load_pi_config(project_root: Path | None = None) -> dict:
    return load_layered_config(
        pkg_default_path=_PI_CONFIG,
        project_root=project_root,
        namespace="harness/pi",
    )


def translate_runner_args(runner_params: Any) -> list[str]:
    """Translate harness-agnostic RunnerParams to pi CLI flags."""
    args: list[str] = []
    if runner_params is None:
        return args
    if runner_params.prompt is not None:
        args.extend(["-p", runner_params.prompt])
    if runner_params.verbose:
        args.append("--verbose")
    if runner_params.mode is not None:
        args.extend(["--mode", runner_params.mode])
    return args


def build_interactive_launch(
    project_root: Path,
    *,
    provider: str,
    model: str,
    agent_runtime: Path,
    mcp_surface=None,
    runner_params: Any = None,
    smoke: bool = False,
) -> ProviderLaunch:
    agent_bin = resolve_agent_bin(agent_runtime)
    agent_dir = agent_runtime / "agent"
    enable_mcp = mcp_surface is not None

    pi_cfg = load_pi_config(project_root)
    tools_cfg = pi_cfg.get("tools", {})
    ext_cfg = pi_cfg.get("extensions", {})
    sandbox_cfg = pi_cfg.get("sandbox", {})
    lockdown_cfg = pi_cfg.get("lockdown", {})

    args: list[str] = ["--provider", provider, "--model", model]

    if smoke:
        args.extend(_SMOKE_ARGS)
    else:
        if tools_cfg.get("no_all", False):
            args.append("--no-tools")
        elif tools_cfg.get("no_builtin", False):
            args.append("--no-builtin-tools")
        elif tools_cfg.get("allow") is not None:
            args.extend(["--tools", ",".join(tools_cfg["allow"])])

        for ext_path in ext_cfg.get("load", []):
            args.extend(["-e", str(ext_path)])

        custom_header = pi_cfg.get("ui", {}).get("custom_header_extension")
        if custom_header:
            args.extend(["-e", str(custom_header)])

        if sandbox_cfg.get("enabled"):
            sandbox_path = sandbox_cfg.get("config_path")
            if sandbox_path:
                args.extend(["--sandbox-config", str(sandbox_path)])

        if lockdown_cfg.get("no_skills", True):
            args.append("--no-skills")
        if lockdown_cfg.get("no_prompt_templates", True):
            args.append("--no-prompt-templates")
        if lockdown_cfg.get("no_context_files", True):
            args.append("--no-context-files")

        for flag in pi_cfg.get("extra_flags", []):
            args.append(flag)

    # Disable extension auto-discovery unconditionally — including in smoke
    # mode, which previously omitted this. Without it, smoke checks silently
    # also loaded whatever extensions are globally configured for pi (e.g.
    # pi-lens), on top of our explicit MCP adapter — extra, unbounded work in
    # exactly the path meant to be a fast, isolated health check, and the
    # likely cause of smoke hanging once the curated MCP set grew past a
    # couple of servers. Only the extensions we explicitly add below load.
    if not enable_mcp:
        args.append("--no-extensions")
    if not smoke:
        args.extend(["--extension", str(agent_dir / "extensions" / "footer.ts")])
        for ext in ext_cfg.get("load", []):
            args.extend(["--extension", str(ext)])

    if mcp_surface is not None:
        args.extend(mcp_surface.extra_args)

    args.extend(translate_runner_args(runner_params))

    environment: dict[str, str] = {
        "HOME": str(agent_runtime),
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(project_root / ".audiagentic" / "sessions"),
    }
    if mcp_surface is not None:
        environment.update(dict(mcp_surface.extra_env))

    return ProviderLaunch(executable=str(agent_bin), args=tuple(args), environment=environment)


__all__ = ["build_interactive_launch", "resolve_agent_bin", "translate_runner_args"]
