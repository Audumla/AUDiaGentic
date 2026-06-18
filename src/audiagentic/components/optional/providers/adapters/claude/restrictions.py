"""Stage-based tool restriction policy for Claude Code hooks.

Pure policy: maps an action tag (plan, implement, review, ...) to the set of
tools permitted at that stage. No coupling to prompt-tag detection or CLI
dispatch — those live in ``hooks.py``.
"""

from __future__ import annotations

from typing import Any


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

    # Load restriction policy
    allowed_tools = _get_allowed_tools_for_stage(action_tag)

    # Filter requested tools to allowed set
    filtered = [t for t in tools_requested if t in allowed_tools]

    return {'allowed_tools': filtered}


def _get_allowed_tools_for_stage(action_tag: str) -> set[str]:
    """
    Get allowed tools for a given action stage.

    Policy from `.claude/rules/review-policy.md` and tag doctrine.
    """
    # Read-only tools available in all stages
    read_tools = {
        'Glob', 'Grep', 'Read',
        'Bash',  # read-only use only (enforced by PreToolUse, not syntax)
        'WebFetch', 'WebSearch',
        'Agent',  # research/exploration agents allowed
    }

    # Write/mutation tools
    write_tools = {
        'Edit', 'Write', 'NotebookEdit',
        'Bash',  # write operations (will be restricted by context in review)
    }

    # Approval/deployment tools
    approval_tools = {
        'Bash',  # potentially destructive (e.g., git push)
    }

    if action_tag == 'review':
        # Review: read-focused only, no writes
        allowed = read_tools | {'TodoWrite'}  # read-only TODOs OK
        allowed.discard('Bash')  # No shell in review
        return allowed

    elif action_tag == 'plan':
        # Plan: explore + read, no implementation
        allowed = read_tools | {'Agent', 'TodoWrite'}
        allowed.discard('Write')
        allowed.discard('Edit')
        allowed.discard('NotebookEdit')
        allowed.discard('Bash')  # No shell in plan
        return allowed

    elif action_tag == 'implement':
        # Implement: full access
        return read_tools | write_tools | approval_tools | {'TodoWrite'}

    elif action_tag == 'audit':
        # Audit: read-focused inspection
        allowed = read_tools | {'TodoWrite'}
        allowed.discard('Bash')
        return allowed

    elif action_tag == 'check-in-prep':
        # Check-in prep: read + doc creation
        allowed = read_tools | {'Write', 'Edit', 'TodoWrite'}
        allowed.discard('Bash')
        return allowed

    else:
        # Unknown tag: default to read-only for safety
        return read_tools
