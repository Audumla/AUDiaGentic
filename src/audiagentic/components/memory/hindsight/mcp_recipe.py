"""Hindsight MCP config entry payload builders.

This module owns only the Hindsight-specific data — the entry name (server name)
and the entry payload schema. The managed-entry lifecycle is handled by provider
machinery via ``_McpConfigAdapter`` (recipes.py) which calls
``providers/services/mcp.py`` sync/status helpers.
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.foundation.mcp import McpServerEntry


def build_hindsight_entry(backend: HindsightBackendConfig) -> dict[str, Any]:
    """Default JSON MCP entry for a Hindsight backend, keyed by transport."""
    if backend.transport == "stdio":
        args = ["--base-url", backend.base_url]
        entry: dict[str, Any] = {"command": "hindsight-mcp", "args": args}
        if backend.api_key:
            entry["env"] = {"HINDSIGHT_API_KEY": backend.api_key}
        if backend.bank_id:
            entry.setdefault("env", {})["HINDSIGHT_BANK_ID"] = backend.bank_id
        return entry
    # sse / http transports point at the MCP endpoint (base URL + /mcp); the
    # bare base URL is the API root and does not speak MCP.
    entry = {"type": backend.transport, "url": backend.mcp_url}
    headers = backend.headers()  # includes Authorization and X-Bank-Id when set
    if headers:
        entry["headers"] = headers
    return entry


def build_hindsight_mcp_entry(backend: HindsightBackendConfig) -> McpServerEntry:
    """Build McpServerEntry directly from HindsightBackendConfig.

    Used on the native reader/writer path (compare + write).
    """
    if backend.transport == "stdio":
        env = {}
        if backend.api_key:
            env["HINDSIGHT_API_KEY"] = backend.api_key
        if backend.bank_id:
            env["HINDSIGHT_BANK_ID"] = backend.bank_id
        return McpServerEntry(
            name=backend.server_name,
            command="hindsight-mcp",
            args=("--base-url", backend.base_url),
            env=env,
        )
    headers = backend.headers()
    return McpServerEntry(
        name=backend.server_name,
        url=backend.mcp_url,
        headers=headers if headers else {},
        transport=backend.transport,
    )


__all__ = [
    "build_hindsight_entry",
    "build_hindsight_mcp_entry",
]
