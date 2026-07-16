"""OpenCode-specific launch declaration for shared ACP transport."""

from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.transports import AcpLaunch


def build_acp_launch(project_root: Path, *, model_id: str | None = None) -> AcpLaunch:
    environment = {}
    if model_id:
        # OpenCode documents inline config as highest-precedence runtime config.
        # This selects profile model without writing user/project config.
        environment["OPENCODE_CONFIG_CONTENT"] = json.dumps({"model": model_id})
    return AcpLaunch(
        executable=require_executable("opencode", "opencode"),
        args=("acp", "--cwd", str(project_root.resolve())),
        environment=environment,
    )
