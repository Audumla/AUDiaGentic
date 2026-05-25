"""Generic MCP server collection and SYSTEM.md injection utilities.

Thin layer: collects MCP server entries from installed/enabled components
and builds harness instruction injections. Format-specific writing and
harness-specific config structure are the responsibility of each harness.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import (
    all_descriptors,
    get_external_probe_results,
    is_enabled,
    is_installed,
)
from audiagentic.runtime.mcp import McpServerEntry


def _python_exe() -> str:
    return sys.executable.replace("\\", "/")


def _src_path() -> str:
    from audiagentic.runtime.harness.pi.paths import find_pi_package_root
    return str(find_pi_package_root(Path(__file__)).parent).replace("\\", "/")


def collect_mcp_servers(project_root: Path | None = None) -> dict[str, McpServerEntry]:
    """Collect MCP server entries from all installed/enabled components.

    External servers whose requirements are missing or probes failed are
    excluded. Returns a dict mapping server name to McpServerEntry.
    """

    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    python = _python_exe()
    src_dir = _src_path()
    servers: dict[str, McpServerEntry] = {}

    for cid, descriptor in all_descriptors().items():
        active = descriptor.core or (
            is_installed(cid, project_root) and is_enabled(cid, project_root)
        )
        if not active:
            continue

        for decl in descriptor.mcp_servers:
            servers[decl.name] = McpServerEntry(
                name=decl.name,
                command=python,
                args=("-m", decl.module) + tuple(decl.args),
                env={"PYTHONPATH": src_dir},
            )

        probe_cache = get_external_probe_results(cid, project_root)
        for ext in descriptor.external_mcp_servers:
            if any(shutil.which(r) is None for r in ext.requires):
                continue
            if ext.probe and probe_cache.get(ext.name) is False:
                continue
            servers[ext.name] = McpServerEntry(
                name=ext.name,
                command=ext.command,
                args=tuple(ext.args),
                env=dict(ext.env),
            )

    return servers


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
            f"- `{component_id}` — {descriptor.description} [status: {status}]"
        )
    return "\n".join(lines)


def build_system_md_injections(project_root: Path | None = None) -> dict[str, str]:
    """Build SYSTEM.md injections from installed components' harness instructions."""
    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    injections: dict[str, str] = {}
    injections["Available components"] = _build_available_components_md(project_root)

    for cid, descriptor in all_descriptors().items():
        if not is_installed(cid, project_root) or not is_enabled(cid, project_root):
            continue
        for instruction in descriptor.harness_instructions:
            if instruction.section in injections:
                injections[instruction.section] += "\n\n" + instruction.content
            else:
                injections[instruction.section] = instruction.content

    return injections


def apply_system_md_injections(content: str, injections: dict[str, str]) -> str:
    """Apply SYSTEM.md injections, replacing each named section's content."""
    for section, injection in injections.items():
        start_marker = f"## {section}\n"
        start_idx = content.find(start_marker)
        if start_idx < 0:
            continue

        after_header = content[start_idx + len(start_marker):]
        lines = after_header.split("\n")
        end_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("## ") or line.startswith("# "):
                end_idx = i
                break

        if end_idx == 0:
            end_idx = len(lines)

        before = content[:start_idx + len(start_marker)]
        after = after_header.split("\n", end_idx)
        after = "\n".join(after[end_idx:]) if end_idx < len(lines) else ""
        content = before + injection.strip() + "\n" + after

    return content
