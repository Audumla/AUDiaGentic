from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.providers.descriptors.base import (
    McpConfigSpec,
    ProviderDescriptor,
)
from audiagentic.components.optional.providers.descriptors.registry import register


def _harness_mcp_path() -> Path:
    from audiagentic.runtime.home import global_harness_runtime
    return global_harness_runtime() / "agent" / "mcp.json"


def _harness_reload(project_root: Path) -> dict[str, Any]:
    from audiagentic.runtime.harness.pi.install import request_runtime_reload
    path = request_runtime_reload(project_root, reason="mcp-refresh-tool")
    return {"marker": str(path)}


register(ProviderDescriptor(
    provider_id="audiagentic-harness",
    display_name="AUDiaGentic Harness",
    description="AUDiaGentic CLI Management interface.",
    access_mode="none",
    mcp_config=McpConfigSpec(
        config_path=_harness_mcp_path,
        format="mcp-json",
        refresh_mode="restart-required",
        reload_fn=_harness_reload,
    ),
))
