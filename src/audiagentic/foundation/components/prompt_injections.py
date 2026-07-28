"""Component-derived prompt sections for provider-owned templates.

The component registry is the authority for installed/enabled contributions.
This helper deliberately lives below provider adapters so they never need to
import runtime orchestration merely to materialize their own prompt files.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.registry import (
    all_descriptors,
    is_enabled,
    is_installed,
)


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
        lines.append(f"- `{component_id}` — {descriptor.description} [status: {status}]")
    return "\n".join(lines)


def build_system_prompt_injections(
    project_root: Path | None = None, *, for_providers: bool = False
) -> dict[str, str]:
    """Build enabled component instructions for a provider or CLI template."""
    project_root = project_root or Path.cwd()
    injections: dict[str, str] = {}
    if not for_providers:
        injections["Available components"] = _build_available_components_md(project_root)

    target = "providers" if for_providers else "audiagentic"
    for component_id, descriptor in all_descriptors().items():
        if not is_installed(component_id, project_root) or not is_enabled(component_id, project_root):
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
    """Replace named markdown sections with bounded component contributions."""
    for section, injection in injections.items():
        start_marker = f"## {section}\n"
        start_idx = content.find(start_marker)
        if start_idx < 0:
            continue
        after_header = content[start_idx + len(start_marker):]
        lines = after_header.split("\n")
        end_idx = next(
            (i for i, line in enumerate(lines) if line.startswith("## ") or line.startswith("# ")),
            len(lines),
        )
        before = content[:start_idx + len(start_marker)]
        after = "\n".join(lines[end_idx:]) if end_idx < len(lines) else ""
        content = before + injection.strip() + "\n" + after
    return content


__all__ = ["apply_system_prompt_injections", "build_system_prompt_injections"]
