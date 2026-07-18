"""Claude Code hook handlers for prompt-trigger integration."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from audiagentic.components.providers.adapters.claude.restrictions import (
    enforce_stage_restrictions,
)
from audiagentic.components.providers.prompt_tags import parse_tagged_prompt
from audiagentic.foundation.cli_io import print_json
from audiagentic.foundation.io import _ensure_dict

__all__ = [
    'detect_and_launch_prompt_tag',
    'enforce_stage_restrictions',
    'UserPromptSubmit_handler',
    'PreToolUse_handler',
    'main',
]

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

    tagged_prompt = parse_tagged_prompt(raw_prompt)
    if tagged_prompt is None:
        return {}
    # A provider hook reports primitive provenance for its requester to launch.
    # It must not parse a requester request or create a requester-owned job.
    return {
        "status": "tag-detected",
        "tag": tagged_prompt.tag,
        "directives": dict(tagged_prompt.directives),
        "prompt-body": tagged_prompt.body,
        "raw-prompt": raw_prompt,
        "provider-id": tagged_prompt.directives.get("provider", "claude"),
        "surface": session_metadata.get("surface", "claude"),
        "session-id": session_metadata.get("session_id") or None,
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
    return _ensure_dict(payload)


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


def _dispatch(handler, *args, payload: dict[str, Any] | None = None) -> int:
    """Load payload, call handler, print result if non-empty."""
    payload = _load_hook_payload() if payload is None else payload
    result = handler(*args, _session_metadata_from_payload(payload))
    if result:
        print_json(result)
    return 0


def _handle_user_prompt_submit_cli(payload: dict[str, Any] | None = None) -> int:
    pl = _load_hook_payload() if payload is None else payload
    raw_prompt = pl.get("prompt") or pl.get("rawPrompt") or pl.get("raw_prompt") or ""
    return _dispatch(UserPromptSubmit_handler, raw_prompt, payload=pl)


def _handle_pre_tool_use_cli(payload: dict[str, Any] | None = None) -> int:
    pl = _load_hook_payload() if payload is None else payload
    tool_name = pl.get("tool_name") or pl.get("toolName") or pl.get("tool") or ""
    action_tag = pl.get("action_tag") or pl.get("actionTag") or pl.get("stage") or ""
    return _dispatch(PreToolUse_handler, str(action_tag), [str(tool_name)] if tool_name else [], payload=pl)


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
