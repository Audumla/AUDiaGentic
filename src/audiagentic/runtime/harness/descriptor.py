from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.providers.descriptors.base import (
    McpConfigSpec,
    ProviderDescriptor,
)
from audiagentic.components.optional.providers.descriptors.registry import register


def _harness_reload(project_root: Path) -> dict[str, Any]:
    from audiagentic.runtime.harness import request_runtime_reload
    path = request_runtime_reload(project_root, reason="mcp-refresh-tool")
    return {"marker": str(path)}


def _mcp_config_path(project_root: Path | None = None) -> Path:
    from audiagentic.runtime.harness import mcp_config_path
    return mcp_config_path(project_root)


def _read_mcp_config(path: Path) -> dict:
    from audiagentic.runtime.harness import read_mcp_config
    return read_mcp_config(path)


def _write_mcp_config(path: Path, entries: dict) -> None:
    from audiagentic.runtime.harness import write_mcp_config
    write_mcp_config(path, entries)


def _remove_mcp_config(path: Path, name: str) -> bool:
    from audiagentic.runtime.harness import remove_mcp_config
    return remove_mcp_config(path, name)


register(ProviderDescriptor(
    provider_id="audiagentic-harness",
    display_name="AUDiaGentic Harness",
    description="AUDiaGentic CLI Management interface.",
    access_mode="none",
    mcp_config=McpConfigSpec(
        config_path=_mcp_config_path,
        reader=_read_mcp_config,
        writer=_write_mcp_config,
        remover=_remove_mcp_config,
        format="harness-mcp-json",
        refresh_mode="restart-required",
        reload_fn=_harness_reload,
    ),
))
