from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.providers.descriptors.base import (
    McpConfigSpec,
    ProviderDescriptor,
)
from audiagentic.components.optional.providers.descriptors.registry import register
from audiagentic.runtime.harness.pi.mcp_format import (
    pi_mcp_path,
    read_pi_mcp_json,
    remove_pi_mcp_json,
    write_pi_mcp_json,
)


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
        config_path=pi_mcp_path,
        reader=read_pi_mcp_json,
        writer=write_pi_mcp_json,
        remover=remove_pi_mcp_json,
        format="pi-mcp-json",
        refresh_mode="restart-required",
        reload_fn=_harness_reload,
    ),
))
