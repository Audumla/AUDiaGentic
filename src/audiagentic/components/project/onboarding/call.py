"""Invoke an AUDiaGentic-owned local MCP tool without installing a provider harness.

The subprocess is the *declared server* and validates the same tool schemas,
lifecycle transitions, and error boundary as a native MCP client. No planning
or ledger contract is duplicated here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.loader import read_component_metadata
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _server_module(project_root: Path, mcp_id: str) -> str:
    modules = [
        declaration.module
        for owner in read_component_metadata(project_root)
        for declaration in owner.mcp_servers
        if declaration.name == mcp_id
    ]
    if len(modules) == 1:
        return modules[0]
    raise AudiaGenticError(
        code="VAL-MCPONB-002",
        kind="validation",
        message="Unknown locally declared MCP server; external servers cannot be invoked via stdio.",
    )


async def call_tool(
    project_root: Path,
    mcp_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    """Call the real MCP server with explicit target root and typed arguments."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise AudiaGenticError(
            code="VAL-MCPONB-003",
            kind="validation",
            message="Target project root must be a directory.",
        )
    module = _server_module(root, mcp_id)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(root),
        env={**os.environ, "AUDIAGENTIC_REPO_ROOT": str(root)},
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
    except Exception as exc:
        raise AudiaGenticError(
            code="VAL-MCPONB-005",
            kind="mcp",
            message="Local MCP server invocation failed.",
        ) from exc

    if result.isError:
        details = "; ".join(
            block.text for block in result.content if block.type == "text"
        )
        raise AudiaGenticError(
            code="VAL-MCPONB-004",
            kind="mcp",
            message=details or "MCP tool rejected the request.",
        )

    if result.structuredContent is not None:
        return result.structuredContent
    text_blocks = [block.text for block in result.content if block.type == "text"]
    if len(text_blocks) == 1:
        import json

        try:
            return json.loads(text_blocks[0])
        except json.JSONDecodeError:
            return text_blocks[0]
    return text_blocks
