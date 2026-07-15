"""Hindsight MCP config entry payload builders.

This module owns only the Hindsight-specific data — the entry name (server name)
and serializable family payload. Provider machinery owns reconciliation.
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.providers.providers_api import ManagedMcpEntry

HINDSIGHT_MANAGED_ID = "ag-hindsight"


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


def build_hindsight_managed_entry(backend: HindsightBackendConfig) -> ManagedMcpEntry:
    """Build one typed managed-MCP family entry."""
    payload = {"name": backend.server_name, **build_hindsight_entry(backend)}
    if "type" in payload:
        payload["transport"] = payload.pop("type")
    return ManagedMcpEntry.from_mapping({"managed_id": HINDSIGHT_MANAGED_ID, **payload})


def hindsight_ownership_scope(backend: HindsightBackendConfig) -> str:
    """Return stable opaque ownership scope for this Hindsight server."""
    return f"memory/hindsight/{backend.server_name}"


__all__ = [
    "build_hindsight_entry",
    "build_hindsight_managed_entry",
    "hindsight_ownership_scope",
]
