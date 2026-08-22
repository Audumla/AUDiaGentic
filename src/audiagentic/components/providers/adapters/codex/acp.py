"""Codex-specific launch declaration for the shared ACP transport.

The official ``codex-acp`` bridge owns the stdio protocol and drives Codex App
Server underneath.  AUDiaGentic model ids may include a reasoning effort as
``model[effort]``; this adapter translates that into the bridge's documented
``CODEX_CONFIG`` startup configuration so a profile cannot accidentally fall
back to the user's global Codex model.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.transports import AcpLaunch

from .model_selection import split_model_selection

_CODEX_ACP_PACKAGE = "@agentclientprotocol/codex-acp@1.6.2"


def _launch_environment(
    model_id: str | None,
    provider_config: dict | None,
) -> dict[str, str]:
    """Build process-local Codex configuration without mutating user state."""

    config: dict[str, object] = {}
    if isinstance(provider_config, dict):
        configured = provider_config.get("codex-config")
        if isinstance(configured, dict):
            config.update(configured)

    model, effort = split_model_selection(model_id)
    if model:
        config["model"] = model
    if effort:
        config["model_reasoning_effort"] = effort

    environment: dict[str, str] = {}
    if config:
        environment["CODEX_CONFIG"] = json.dumps(config, separators=(",", ":"))
    if isinstance(provider_config, dict):
        codex_home = provider_config.get("codex-home")
        if isinstance(codex_home, str) and codex_home.strip():
            environment["CODEX_HOME"] = os.path.expandvars(codex_home.strip())
    return environment


def build_acp_launch(
    project_root: Path,
    *,
    model_id: str | None = None,
    provider_config: dict | None = None,
    request_runtime_root: Path | None = None,
    mcp_surface=None,
) -> AcpLaunch:
    # The gateway supplies these common ACP-builder hooks for every session.
    # Codex does not currently need a per-request runtime directory or MCP
    # entries, but accepting them keeps the adapter compatible with the
    # provider-neutral preparation seam (and avoids silently downgrading a
    # declared session surface to unsupported).
    del project_root, request_runtime_root, mcp_surface
    environment = _launch_environment(model_id, provider_config)
    configured = provider_config.get("acp-executable") if isinstance(provider_config, dict) else None
    if isinstance(configured, str) and configured.strip():
        configured_path = shutil.which(configured.strip()) or configured.strip()
        return AcpLaunch(executable=configured_path, args=(), environment=environment)

    # Prefer a locally installed codex-acp binary.  The pinned npx fallback is
    # intentionally deterministic while the managed auxiliary-install seam
    # (AS13/AS98) is completed; it is never allowed to select a floating latest
    # bridge version.
    direct = shutil.which("codex-acp")
    if direct:
        return AcpLaunch(executable=direct, args=(), environment=environment)
    return AcpLaunch(
        executable=require_executable("codex", "npx"),
        args=("-y", _CODEX_ACP_PACKAGE),
        environment=environment,
    )
