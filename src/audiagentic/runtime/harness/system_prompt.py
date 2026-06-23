"""Harness-generic system prompt injection from installed components.

Scans component descriptors for harness_instructions and builds section
injections that any harness can apply to its system prompt template.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.components.base import (
    ComponentDescriptor,
    HarnessInstruction,
)
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import (
    all_descriptors,
    is_enabled,
    is_installed,
)

logger = logging.getLogger(__name__)


def derive_harness_instructions(descriptor: ComponentDescriptor) -> tuple[HarnessInstruction, ...]:
    """Derive harness instructions from MCP server declarations.

    Reads `direct-tools` and `tool-descriptions` from MCP server declarations
    and generates a harness instruction section. Components can still provide
    custom harness instructions, but the default is derived.

    Returns an empty tuple if the component has no MCP servers with direct tools.
    """
    if not descriptor.mcp_servers:
        return ()

    sections: dict[str, list[str]] = {}

    for server in descriptor.mcp_servers:
        if not server.direct_tools or not isinstance(server.direct_tools, list):
            continue

        section = f"MCP tools ({server.name})"
        if section not in sections:
            sections[section] = []

        lines = [f"## {section}", ""]
        if server.description:
            lines.append(f"{server.description}")
            lines.append("")

        lines.append("Available tools:")
        for tool in server.direct_tools:
            desc = server.tool_descriptions.get(tool, "")
            if desc:
                lines.append(f"- `{tool}`: {desc}")
            else:
                lines.append(f"- `{tool}`")
        lines.append("")

        sections[section] = lines

    if not sections:
        return ()

    instructions = []
    for section, lines in sections.items():
        instructions.append(HarnessInstruction(
            section=section,
            content="\n".join(lines),
            description=f"Derived harness instructions for {descriptor.component_id}",
            propagate=descriptor.mcp_servers[0].propagate if descriptor.mcp_servers else "audiagentic",
        ))

    return tuple(instructions)


def check_harness_instruction_drift(descriptor: ComponentDescriptor) -> list[str]:
    """Check for drift between MCP instructions and harness instructions.

    Returns a list of warnings if MCP server declarations and harness instructions
    describe different tool sets. Empty list if no drift detected.
    """
    warnings = []

    # Build set of tools from MCP declarations
    mcp_tools = set()
    for server in descriptor.mcp_servers:
        if isinstance(server.direct_tools, list):
            mcp_tools.update(server.direct_tools)

    # Build set of tools from harness instructions
    harness_tools = set()
    for instruction in descriptor.harness_instructions:
        # Extract tool references from instruction content
        import re  # noqa: PLC0415
        for match in re.finditer(r"`(\w+)`", instruction.content):
            harness_tools.add(match.group(1))

    # Check for drift
    if mcp_tools and harness_tools:
        only_in_mcp = mcp_tools - harness_tools
        only_in_harness = harness_tools - mcp_tools
        if only_in_mcp:
            warnings.append(
                f"Component {descriptor.component_id}: tools in MCP but not harness: {sorted(only_in_mcp)}"
            )
        if only_in_harness:
            warnings.append(
                f"Component {descriptor.component_id}: tools in harness but not MCP: {sorted(only_in_harness)}"
            )

    return warnings


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


def build_system_prompt_injections(project_root: Path | None = None, *, for_providers: bool = False) -> dict[str, str]:
    """Build system prompt injections from installed components' harness instructions.

    When for_providers=True, only includes instructions with propagate in ('providers', 'both').
    When for_providers=False (default), only includes instructions with propagate in ('cli', 'both').
    """
    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    injections: dict[str, str] = {}
    if not for_providers:
        injections["Available components"] = _build_available_components_md(project_root)

    target = "providers" if for_providers else "audiagentic"
    for cid, descriptor in all_descriptors().items():
        if not is_installed(cid, project_root) or not is_enabled(cid, project_root):
            continue
        for instruction in descriptor.harness_instructions:
            if target not in instruction.propagate:
                continue
            if instruction.section in injections:
                injections[instruction.section] += "\n\n" + instruction.content
            else:
                injections[instruction.section] = instruction.content

    return injections


def apply_system_prompt_injections(content: str, injections: dict[str, str]) -> str:
    """Apply injections, replacing each named section's content."""
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
