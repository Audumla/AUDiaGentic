"""Small, pure mappings used by the ACP adapter."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


class UnsupportedAcpOperation(RuntimeError):
    """The canonical Agents API does not support an ACP operation."""


def validate_cwd(project_root: Path, cwd: str) -> None:
    candidate = Path(cwd).resolve()
    root = project_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("ACP cwd must remain inside the bound project root")


def reject_client_extensions(
    mcp_servers: Iterable[Any] | None,
    additional_directories: Iterable[str] | None,
) -> None:
    if mcp_servers:
        raise UnsupportedAcpOperation("client MCP server injection is not supported")
    if additional_directories:
        raise UnsupportedAcpOperation("additional_directories is not supported")


def text_from_prompt(prompt: Iterable[Any]) -> str:
    parts: list[str] = []
    for block in prompt:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, Mapping):
            text = block.get("text")
        if text:
            parts.append(str(text))
    if not parts:
        raise ValueError("ACP prompt must contain text")
    return "\n".join(parts)
