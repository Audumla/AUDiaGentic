"""Pi interactive (TUI) launch builder.

Builds the command/environment for launching the stock `pi` binary for a
human-facing interactive session -- distinct from acp.py's build_acp_launch
(the headless `pi-acp` RPC bridge for programmatic sessions).

AUDiaGentic does NOT customize the harness for interactive use: no injected
extensions, no bundled UI. It only (a) points Pi at an isolated home and
materialized agent config via env, (b) sets Pi's own stock CLI flags for
tool/lockdown policy, and (c) lets the MCP surface deliver AG's projected MCP
servers. Kept hand-written (rather than a declarative recipe) only because of
the isolation env block and the MCP-coordinated ``--no-extensions`` gate; it
still returns the same ProviderLaunch every launch kind produces.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.config import load_layered_config
from audiagentic.foundation.paths.package import PACKAGE_ROOT
from audiagentic.foundation.transports import ProviderLaunch

_PI_CONFIG = PACKAGE_ROOT / "config" / "provisioning" / "harness" / "pi.yaml"

# Stock-Pi flags for a fast, isolated health check: no session, no tools, no
# discovery of anything, one fixed prompt whose exact echo proves the round trip.
_SMOKE_ARGS: tuple[str, ...] = (
    "--no-session", "--no-tools", "--no-context-files",
    "--no-skills", "--no-prompt-templates", "--no-themes",
    "--thinking", "off",
    "--system-prompt", "Return only the exact requested string. No markdown. No explanation.",
    "-p", "Return only this exact ASCII string, no punctuation, no markdown: audiagentic-agent-local-ok",
)

# tools.mode -> Pi built-in-tool flag. none=all off, mcp-only=built-ins off
# (MCP + explicit tools remain), full=Pi defaults (no flag).
_TOOLS_MODE_FLAGS: dict[str, list[str]] = {
    "none": ["--no-tools"],
    "mcp-only": ["--no-builtin-tools"],
    "full": [],
}


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
    executable = require_executable("pi", "pi")
    agent_dir = agent_runtime / "agent"
    enable_mcp = mcp_surface is not None

    pi_cfg = load_pi_config(project_root)
    lockdown = pi_cfg.get("lockdown", {})

    args: list[str] = ["--provider", provider, "--model", model]

    if smoke:
        args.extend(_SMOKE_ARGS)
    else:
        args.extend(_TOOLS_MODE_FLAGS.get(pi_cfg.get("tools", {}).get("mode", "mcp-only"), []))
        if lockdown.get("no_skills", True):
            args.append("--no-skills")
        if lockdown.get("no_prompt_templates", True):
            args.append("--no-prompt-templates")
        if lockdown.get("no_context_files", True):
            args.append("--no-context-files")

    # Disable Pi's extension auto-discovery so a stock, isolated session loads
    # nothing of its own. When MCP is enabled the MCP surface already emits
    # --no-extensions (alongside the MCP adapter it explicitly loads), so add it
    # here only for the no-MCP case to avoid a duplicate flag.
    if not enable_mcp:
        args.append("--no-extensions")

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

    return ProviderLaunch(executable=executable, args=tuple(args), environment=environment)


__all__ = ["build_interactive_launch", "translate_runner_args"]
