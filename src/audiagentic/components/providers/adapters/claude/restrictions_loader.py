"""Tool restriction policy loader for Claude adapter.

Loads stage-based tool policies from YAML config. The claude adapter
owns the tool names; the policies define which tools are allowed per
action tag. Unknown action tags fall back to read-only.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.package import SRC_ROOT

logger = logging.getLogger(__name__)

_DEFAULT_POLICIES_PATH = SRC_ROOT / "audiagentic" / "config" / "components" / "providers" / "claude-restrictions.yaml"


def _load_policies(path: Path | None = None) -> dict[str, Any]:
    """Load the tool restriction policies from YAML."""
    policy_path = path or _DEFAULT_POLICIES_PATH
    if not policy_path.exists():
        logger.warning("claude restriction policies not found at %s; using defaults", policy_path)
        return {}
    data = load_yaml_file(policy_path)
    if not isinstance(data, dict):
        logger.warning("claude restriction policies has unexpected format; using defaults")
        return {}
    return data


def _build_tool_registry(policies: dict[str, Any]) -> dict[str, set[str]]:
    """Build a lookup dict: action_tag -> allowed tools."""
    policies_data = policies.get("policies", {})
    actions = policies_data.get("actions", {})
    default = policies_data.get("default", {})
    default_tools = set(default.get("allowed", []))

    registry: dict[str, set[str]] = {}
    for action_tag, action_cfg in actions.items():
        allowed = action_cfg.get("allowed", [])
        if isinstance(allowed, list):
            registry[action_tag] = set(t for t in allowed if isinstance(t, str))
        else:
            registry[action_tag] = default_tools

    return registry


def get_allowed_tools(action_tag: str) -> set[str]:
    """Get the allowed tools for a given action tag.

    Args:
        action_tag: The canonical action tag (e.g. 'ag-review', 'ag-plan').

    Returns:
        Set of allowed tool names. Falls back to read-only for unknown tags.
    """
    policies = _load_policies()
    registry = _build_tool_registry(policies)
    default_tools = set(policies.get("policies", {}).get("default", {}).get("allowed", []))
    return registry.get(action_tag, set(default_tools))
