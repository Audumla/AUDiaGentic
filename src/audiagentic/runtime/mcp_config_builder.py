"""Dynamic MCP config and harness instruction generation from installed components.

Builds mcp.json and SYSTEM.md by introspecting installed components and their
declared MCP server configurations and harness instructions.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.base import (
    ExternalMcpServerDeclaration,
    McpServerDeclaration,
)
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed


def _get_python_path() -> str:
    """Return the Python executable path."""
    return sys.executable.replace("\\", "/")


def _get_src_path() -> str:
    """Return the source directory path for PYTHONPATH."""
    return str(Path(__file__).resolve().parents[3]).replace("\\", "/")


def _build_available_components_md(project_root: Path) -> str:
    lines = [
        "Use `audiagentic_project_list_components` when user asks what components exist,",
        "what they do, or whether install/enable needed.",
        "",
    ]

    for component_id, descriptor in sorted(all_descriptors().items()):
        installed = is_installed(component_id, project_root)
        enabled = is_enabled(component_id, project_root) if installed else None
        status = "installed/enabled" if installed and enabled else (
            "installed/disabled" if installed else "not installed"
        )
        lines.append(
            f"- `{component_id}` — {descriptor.description} "
            f"[status: {status}]"
        )

    return "\n".join(lines)


def build_mcp_config(
    project_root: Path | None = None,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build mcp.json config from installed components' MCP server declarations.

    Args:
        project_root: Project root path (defaults to current working directory)
        extra_config: Additional config to merge (e.g. from ag.yaml)

    Returns:
        dict suitable for json.dump to mcp.json
    """
    if project_root is None:
        project_root = Path.cwd()

    if extra_config is None:
        extra_config = {}

    register_all_components()

    mcp_cfg = extra_config.get("mcp", {})
    if not mcp_cfg.get("enabled", True):
        return {"settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": False}, "mcpServers": {}}

    extra_args: list[str] = mcp_cfg.get("extra_server_args", [])
    python = _get_python_path()
    src_dir = _get_src_path()

    def _build_server_decl(server_decl: McpServerDeclaration) -> dict[str, Any]:
        args = list(server_decl.args) + extra_args
        result: dict[str, Any] = {
            "command": python,
            "args": ["-m", server_decl.module] + args,
            "env": {"PYTHONPATH": src_dir},
            "lifecycle": "lazy",
        }
        if server_decl.direct_tools is True or server_decl.direct_tools:
            result["directTools"] = server_decl.direct_tools
        return result

    def _build_external_decl(ext: ExternalMcpServerDeclaration) -> dict[str, Any] | None:
        if any(shutil.which(r) is None for r in ext.requires):
            return None
        if ext.probe:
            import subprocess
            result = subprocess.run(list(ext.probe), capture_output=True)
            if result.returncode != 0:
                return None
        entry: dict[str, Any] = {
            "command": ext.command,
            "args": list(ext.args),
            "lifecycle": "lazy",
        }
        if ext.env:
            entry["env"] = dict(ext.env)
        return entry

    servers: dict[str, dict[str, Any]] = {}

    for cid, descriptor in all_descriptors().items():
        active = descriptor.core or (
            is_installed(cid, project_root) and is_enabled(cid, project_root)
        )
        if not active:
            continue
        for server_decl in descriptor.mcp_servers:
            servers[server_decl.name] = _build_server_decl(server_decl)
        for ext in descriptor.external_mcp_servers:
            entry = _build_external_decl(ext)
            if entry is not None:
                servers[ext.name] = entry

    settings = {
        "toolPrefix": "mcp",
        "idleTimeout": 10,
        "directTools": True,
    }

    return {"settings": settings, "mcpServers": servers}


def build_system_md_injections(
    project_root: Path | None = None,
) -> dict[str, str]:
    """Build SYSTEM.md injections from installed components' harness instructions.

    Returns a dict mapping section names to their markdown content.

    Args:
        project_root: Project root path (defaults to current working directory)

    Returns:
        dict mapping section names to markdown content
    """
    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    injections: dict[str, str] = {}

    injections["Available components"] = _build_available_components_md(project_root)

    for cid, descriptor in all_descriptors().items():
        if not is_installed(cid, project_root):
            continue
        if not is_enabled(cid, project_root):
            continue

        for instruction in descriptor.harness_instructions:
            # Merge content for same section
            if instruction.section in injections:
                injections[instruction.section] += "\n\n" + instruction.content
            else:
                injections[instruction.section] = instruction.content

    return injections


def apply_system_md_injections(
    content: str,
    injections: dict[str, str],
) -> str:
    """Apply SYSTEM.md injections to existing content.

    Replaces section content with injected content.

    Args:
        content: Existing SYSTEM.md content
        injections: Dict mapping section names to markdown content

    Returns:
        Updated SYSTEM.md content
    """
    for section, injection in injections.items():
        # Find the section header (with ## prefix) and its content
        start_marker = f"## {section}\n"
        start_idx = content.find(start_marker)

        if start_idx < 0:
            continue

        # Find the next section or end of content
        after_header = content[start_idx + len(start_marker):]
        lines = after_header.split("\n")
        end_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("## ") or line.startswith("# "):
                end_idx = i
                break

        if end_idx == 0:
            end_idx = len(lines)

        # Replace the section content
        before = content[:start_idx + len(start_marker)]
        after = after_header.split("\n", end_idx)
        after = "\n".join(after[end_idx:]) if end_idx < len(lines) else ""

        content = before + injection.strip() + "\n" + after

    return content
