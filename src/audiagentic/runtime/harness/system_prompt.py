"""Harness-generic system prompt injection from installed components.

Builds the `Available components` registry overview and applies any
component-supplied `harness-instructions` doctrine sections that match a
template header. Per-tool definitions are component-owned and advertised over
MCP via `tool-descriptions`; the system prompt carries no consolidated tool
catalog.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.components.registry import (
    all_descriptors,
    is_enabled,
    is_installed,
)

logger = logging.getLogger(__name__)


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
