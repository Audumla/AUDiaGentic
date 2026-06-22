"""Stage-based tool restriction policy for Claude Code hooks.

Delegates to the config-driven policy loader. The claude adapter owns the
tool names; the policies are declared in YAML and loaded at runtime.
"""

from __future__ import annotations

from typing import Any

from .restrictions_loader import get_allowed_tools


def enforce_stage_restrictions(
    action_tag: str,
    tools_requested: list[str],
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    PreToolUse hook: enforce stage restrictions per action tag.

    Args:
        action_tag: The detected action tag (plan, implement, review, etc.)
        tools_requested: List of tool names Claude wants to use
        session_metadata: Session context

    Returns:
        Dict with 'allowed_tools' list
    """
    if not action_tag:
        return {'allowed_tools': tools_requested}

    allowed_tools = get_allowed_tools(action_tag)

    filtered = [t for t in tools_requested if t in allowed_tools]

    return {'allowed_tools': filtered}
