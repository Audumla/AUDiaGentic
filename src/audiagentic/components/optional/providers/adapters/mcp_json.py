"""Compatibility exports for standard MCP JSON helpers."""
from __future__ import annotations

from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)

__all__ = ["read_mcp_json", "remove_mcp_json", "write_mcp_json"]
