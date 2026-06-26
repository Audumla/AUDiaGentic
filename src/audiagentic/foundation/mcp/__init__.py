"""Foundation MCP package — canonical MCP server entry type."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpServerEntry:
    """Generic representation of an MCP server for harness consumption.

    Supports both stdio (command/args/env) and remote (url/headers/transport)
    server entries. Use :attr:`is_remote` to distinguish the two modes.
    """
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    transport: str | None = None  # "http" | "sse"

    @property
    def is_remote(self) -> bool:
        """True if this entry uses a remote URL instead of stdio command."""
        return self.url is not None


__all__ = ["McpServerEntry"]
