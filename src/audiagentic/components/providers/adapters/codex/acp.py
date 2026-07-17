"""Codex-specific launch declaration for shared ACP transport.

Codex has no native ``--acp`` mode; the official bridge is the
``@agentclientprotocol/codex-acp`` adapter, which exposes an ACP server over
stdio and drives Codex App Server underneath. Exposing ``build_acp_launch``
here opts the codex provider into gateway live sessions (plan agent-sessions
AS04 capability seam / AS13).

Known limits of this stdio path (AS13 notes):
- the ACP client owns the session — this does not attach to an already-open
  interactive Codex TUI (that needs the App Server transport, AS14);
- model selection currently rides on Codex's own configuration (config.toml /
  CODEX_HOME); ``model_id`` passthrough is pending empirical verification of
  the adapter's argument forwarding — until then a requested model that
  differs from the codex default is NOT applied by this launch.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.transports import AcpLaunch

_CODEX_ACP_PACKAGE = "@agentclientprotocol/codex-acp"


def build_acp_launch(project_root: Path, *, model_id: str | None = None) -> AcpLaunch:
    # Prefer a locally installed codex-acp binary; fall back to npx so the
    # adapter works without a global install (npx resolves and caches it).
    direct = shutil.which("codex-acp")
    if direct:
        return AcpLaunch(executable=direct, args=(), environment={})
    return AcpLaunch(
        executable=require_executable("codex", "npx"),
        args=("-y", _CODEX_ACP_PACKAGE),
        environment={},
    )
