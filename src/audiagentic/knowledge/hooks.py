from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import KnowledgeConfig


def load_hooks(config: KnowledgeConfig) -> list[dict[str, Any]]:
    """Load hook configurations from the hooks.yml file.

    Hooks define eligibility rules for source files before they trigger
    knowledge sync actions. This function loads the raw configuration
    without applying any evaluation logic.

    Args:
        config: KnowledgeConfig instance with path to hooks config file

    Returns:
        List of hook configuration dictionaries
    """
    path = config.hook_config_file
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hooks = data.get("hooks", [])
    if not isinstance(hooks, list):
        return []
    return [hook for hook in hooks if isinstance(hook, dict)]


def evaluate_source(config: KnowledgeConfig, relative_path: str) -> list[dict[str, Any]]:
    """Evaluate a source file against all applicable hooks.

    This function applies the eligibility rules defined in hooks.yml to
    determine whether a source file should trigger knowledge sync actions.

    Evaluation flow:
    1. Load all hooks from config
    2. Filter hooks by applies_to path patterns
    3. Evaluate eligibility rules for each matching hook
    4. Return evaluation results with eligibility status and reasons

    Args:
        config: KnowledgeConfig instance
        relative_path: Path to source file relative to project root

    Returns:
        List of evaluation results, each containing:
        - hook_id: ID of the hook that was evaluated
        - kind: Type of hook
        - eligible: Whether the source passed this hook's eligibility rules
        - action: Action to take if eligible
        - reasons: List of reasons for eligibility decision
    """
    hooks = load_hooks(config)
    source_path = config.root / relative_path
    text = source_path.read_text(encoding="utf-8", errors="replace") if source_path.exists() else ""
    evaluations: list[dict[str, Any]] = []

    for hook in hooks:
        applies_to = [str(x) for x in hook.get("applies_to", []) or []]
        if applies_to and not _path_matches(relative_path, applies_to):
            continue

        eligibility = (
            hook.get("eligibility", {}) if isinstance(hook.get("eligibility"), dict) else {}
        )
        eligible = True
        reasons: list[str] = []

        # Apply rejection rules (path-based)
        for token in [str(x) for x in eligibility.get("reject_when_path_contains", []) or []]:
            if token and token in relative_path:
                eligible = False
                reasons.append(f"rejected_by_path:{token}")

        # Apply rejection rules (content-based)
        for token in [str(x) for x in eligibility.get("reject_when_content_contains", []) or []]:
            if token and token in text:
                eligible = False
                reasons.append(f"rejected_by_content:{token}")

        # Apply allow rules (content-based)
        allow_tokens = [
            str(x) for x in eligibility.get("allow_when_content_contains_any", []) or []
        ]
        if allow_tokens:
            if any(token and token in text for token in allow_tokens):
                reasons.append("allowed_by_content_marker")
            else:
                reasons.append("no_allow_marker_found")
                eligible = False

        evaluations.append(
            {
                "hook_id": hook.get("id"),
                "kind": hook.get("kind"),
                "eligible": eligible,
                "action": hook.get("action"),
                "action_args": hook.get("action_args", {}),
                "reasons": reasons,
            }
        )

    return evaluations


def _path_matches(relative_path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the given glob patterns.

    Args:
        relative_path: Path to check
        patterns: List of glob patterns

    Returns:
        True if path matches any pattern, False otherwise
    """
    path = Path(relative_path)
    return any(path.match(pattern) for pattern in patterns)
