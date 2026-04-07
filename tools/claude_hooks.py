"""Claude Code hook handlers for prompt-trigger bridge integration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Canonical tags recognized by the shared bridge
CANONICAL_TAGS = {'plan', 'implement', 'review', 'audit', 'check-in-prep'}


def detect_and_launch_prompt_tag(
    raw_prompt: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    UserPromptSubmit hook: detect canonical tag and route to shared bridge.

    Args:
        raw_prompt: Raw user prompt text
        session_metadata: Session context (surface, session_id, workspace_root, etc.)

    Returns:
        Dict with launch context if tag detected, empty dict otherwise
    """
    if not raw_prompt:
        return {}

    # Extract first non-empty line
    first_line = None
    for line in raw_prompt.split('\n'):
        if line.strip():
            first_line = line.strip()
            break

    if not first_line:
        return {}

    # Detect tag starting with @ (canonical or aliased)
    if not first_line.startswith('@'):
        return {}  # No tag, pass through to normal planning

    # Extract tag token (everything up to space or end of line)
    tag_token = first_line[1:].split()[0] if first_line[1:] else ''
    if not tag_token:
        return {}

    # The shared bridge will handle tag/provider alias resolution
    # We just need to detect that a tag-like token is present
    tag_found = '@' + tag_token

    # Tag detected: normalize and route to shared bridge
    return _invoke_shared_bridge(
        raw_prompt=raw_prompt,
        first_line=first_line,
        tag=tag_found,
        session_metadata=session_metadata,
    )


def _invoke_shared_bridge(
    raw_prompt: str,
    first_line: str,
    tag: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Invoke shared prompt-trigger bridge and return result."""
    try:
        workspace_root = session_metadata.get('workspace_root', '.')
        surface = session_metadata.get('surface', 'cli')
        session_id = session_metadata.get('session_id', '')

        # Extract parameters from first line (e.g., "@plan provider=cline id=job_001")
        params = _parse_first_line_params(first_line)
        provider_id = params.get('provider', 'claude')

        # Build bridge invocation
        bridge_cmd = [
            sys.executable,
            str(Path(__file__).parent / 'claude_prompt_trigger_bridge.py'),
            '--project-root', str(workspace_root),
            '--surface', surface,
            '--provider-id', provider_id,
        ]

        if session_id:
            bridge_cmd.extend(['--session-id', session_id])

        # Invoke shared bridge
        result = subprocess.run(
            bridge_cmd,
            input=raw_prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            # Bridge failed; return error context
            try:
                return json.loads(result.stdout)
            except (json.JSONDecodeError, ValueError):
                return {
                    'status': 'error',
                    'kind': 'bridge_invocation_failed',
                    'message': result.stderr or 'Bridge invocation failed with no error output',
                }

        # Parse and return bridge result
        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        return {
            'status': 'error',
            'kind': 'timeout',
            'message': 'Shared bridge invocation timed out after 30 seconds',
        }
    except Exception as exc:
        return {
            'status': 'error',
            'kind': 'exception',
            'message': f'Hook handler error: {type(exc).__name__}: {exc}',
        }


def _parse_first_line_params(first_line: str) -> dict[str, str]:
    """
    Parse inline parameters from first line.

    Examples:
        "@plan provider=cline" → {'provider': 'cline'}
        "@review id=job_001 provider=claude" → {'id': 'job_001', 'provider': 'claude'}
    """
    params = {}
    tokens = first_line.split()

    for token in tokens[1:]:  # Skip the tag itself
        if '=' in token:
            key, value = token.split('=', 1)
            params[key.strip()] = value.strip()

    return params


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


# Hook exports for Claude settings configuration

def UserPromptSubmit_handler(
    raw_prompt: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Exported hook handler for Claude settings.json UserPromptSubmit."""
    return detect_and_launch_prompt_tag(raw_prompt, session_metadata)


def PreToolUse_handler(
    action_tag: str,
    tools_requested: list[str],
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Exported hook handler for Claude settings.json PreToolUse."""
    return enforce_stage_restrictions(action_tag, tools_requested, session_metadata)


def _load_hook_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_root": payload.get("workspaceRoot")
        or payload.get("workspace_root")
        or payload.get("cwd")
        or ".",
        "surface": payload.get("surface") or "claude",
        "session_id": payload.get("sessionId") or payload.get("session_id") or "",
    }


def _handle_user_prompt_submit_cli() -> int:
    payload = _load_hook_payload()
    raw_prompt = (
        payload.get("prompt")
        or payload.get("rawPrompt")
        or payload.get("raw_prompt")
        or ""
    )
    result = UserPromptSubmit_handler(raw_prompt, _session_metadata_from_payload(payload))
    if result:
        print(json.dumps(result))
    return 0


def _handle_pre_tool_use_cli() -> int:
    payload = _load_hook_payload()
    tool_name = payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or ""
    action_tag = (
        payload.get("action_tag")
        or payload.get("actionTag")
        or payload.get("stage")
        or ""
    )
    result = PreToolUse_handler(
        str(action_tag),
        [str(tool_name)] if tool_name else [],
        _session_metadata_from_payload(payload),
    )
    if result:
        print(json.dumps(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude hook command adapter.")
    parser.add_argument("hook", choices=["user-prompt-submit", "pre-tool-use"])
    args = parser.parse_args(argv)
    if args.hook == "user-prompt-submit":
        return _handle_user_prompt_submit_cli()
    return _handle_pre_tool_use_cli()


if __name__ == "__main__":
    raise SystemExit(main())
