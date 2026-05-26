"""Foundation MCP package — canonical MCP server entry type."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpServerEntry:
    """Generic representation of an MCP server for harness consumption."""
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


__all__ = ["McpServerEntry"]
