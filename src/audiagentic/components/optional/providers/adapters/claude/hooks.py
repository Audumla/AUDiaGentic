"""Claude Code hook handlers for prompt-trigger integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from audiagentic.cli_io import print_json
from audiagentic.components.optional.providers.adapters.claude.restrictions import (
    enforce_stage_restrictions,
)

__all__ = [
    'detect_and_launch_prompt_tag',
    'enforce_stage_restrictions',
    'UserPromptSubmit_handler',
    'PreToolUse_handler',
    'main',
]

CANONICAL_TAGS = {'plan', 'implement', 'review', 'audit', 'check-in-prep'}
HOOK_USER_PROMPT_SUBMIT = 'user-prompt-submit'
HOOK_PRE_TOOL_USE = 'pre-tool-use'


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

    return _invoke_prompt_launch(
        raw_prompt=raw_prompt,
        first_line=first_line,
        tag=tag_found,
        session_metadata=session_metadata,
    )


def _invoke_prompt_launch(
    raw_prompt: str,
    first_line: str,
    tag: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    try:
        from audiagentic.components.optional.agent_jobs.prompt_launch import launch_prompt_request
        from audiagentic.components.optional.agent_jobs.prompt_parser import (
            parse_prompt_launch_request,
        )

        workspace_root = session_metadata.get('workspace_root', '.')
        surface = session_metadata.get('surface', 'cli')
        session_id = session_metadata.get('session_id', '')
        params = _parse_first_line_params(first_line)
        provider_id = params.get('provider', 'claude')

        request = parse_prompt_launch_request(
            raw_prompt,
            surface=surface,
            provider_id=provider_id,
            session_id=session_id or None,
            allow_adhoc_target=False,
            project_root=Path(workspace_root),
        )
        return launch_prompt_request(Path(workspace_root), request)

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
        "@plan provider=cline" -> {'provider': 'cline'}
        "@review id=job_001 provider=claude" -> {'id': 'job_001', 'provider': 'claude'}
    """
    params = {}
    tokens = first_line.split()

    for token in tokens[1:]:  # Skip the tag itself
        if '=' in token:
            key, value = token.split('=', 1)
            params[key.strip()] = value.strip()

    return params


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


def _resolve_hook_name(explicit_hook: str | None, payload: dict[str, Any]) -> str:
    """Resolve the hook name from argv or the Claude payload."""
    if explicit_hook:
        return explicit_hook

    payload_hook = (
        payload.get('hook')
        or payload.get('hook_name')
        or payload.get('hookName')
    )
    if isinstance(payload_hook, str):
        lowered = payload_hook.strip().lower()
        if lowered in {'userpromptsubmit', 'user-prompt-submit'}:
            return HOOK_USER_PROMPT_SUBMIT
        if lowered in {'pretooluse', 'pre-tool-use'}:
            return HOOK_PRE_TOOL_USE

    if any(payload.get(key) for key in ('prompt', 'rawPrompt', 'raw_prompt')):
        return HOOK_USER_PROMPT_SUBMIT

    if any(payload.get(key) for key in ('tool_name', 'toolName', 'tool', 'action_tag', 'actionTag', 'stage')):
        return HOOK_PRE_TOOL_USE

    # Default to prompt-submit so a missing argv hook does not fail the hook chain.
    return HOOK_USER_PROMPT_SUBMIT


def _session_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_root": payload.get("workspaceRoot")
        or payload.get("workspace_root")
        or payload.get("cwd")
        or ".",
        "surface": payload.get("surface") or "claude",
        "session_id": payload.get("sessionId") or payload.get("session_id") or "",
    }


def _handle_user_prompt_submit_cli(payload: dict[str, Any] | None = None) -> int:
    payload = _load_hook_payload() if payload is None else payload
    raw_prompt = (
        payload.get("prompt")
        or payload.get("rawPrompt")
        or payload.get("raw_prompt")
        or ""
    )
    result = UserPromptSubmit_handler(raw_prompt, _session_metadata_from_payload(payload))
    if result:
        print_json(result)
    return 0


def _handle_pre_tool_use_cli(payload: dict[str, Any] | None = None) -> int:
    payload = _load_hook_payload() if payload is None else payload
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
        print_json(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude hook command adapter.")
    parser.add_argument("hook", nargs="?", choices=[HOOK_USER_PROMPT_SUBMIT, HOOK_PRE_TOOL_USE])
    args = parser.parse_args(argv)

    payload = _load_hook_payload()
    hook_name = _resolve_hook_name(args.hook, payload)

    if hook_name == HOOK_USER_PROMPT_SUBMIT:
        return _handle_user_prompt_submit_cli(payload)
    return _handle_pre_tool_use_cli(payload)


if __name__ == "__main__":
    raise SystemExit(main())
