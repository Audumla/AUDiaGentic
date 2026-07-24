"""OpenCode interactive (TUI) launch builder.

Builds the command/environment for launching the `opencode` binary itself
for a human-facing interactive session -- the provider-owned home for what
used to live in runtime/harness/opencode/runner/__init__.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports import ProviderLaunch


def translate_runner_args(runner_params: Any) -> list[str]:
    """Translate harness-agnostic RunnerParams to opencode CLI flags."""
    args: list[str] = []
    if runner_params is None:
        return args
    if runner_params.mode == "json":
        args.extend(["--output-format", "json"])
    if runner_params.prompt is not None:
        args.extend(["--message", runner_params.prompt])
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
    del provider, model, agent_runtime, smoke  # opencode's CLI needs neither for launch

    executable = shutil.which("opencode")
    if executable is None:
        raise make_error(
            prefix="CFG",
            component="OCINST",
            number=3,
            kind="opencode-harness",
            message="opencode CLI not found on PATH",
        )

    args = translate_runner_args(runner_params)
    environment: dict[str, str] = {}
    if mcp_surface is not None:
        environment.update(dict(mcp_surface.extra_env))

    return ProviderLaunch(executable=executable, args=tuple(args), environment=environment)


__all__ = ["build_interactive_launch", "translate_runner_args"]
