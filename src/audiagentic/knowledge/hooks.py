from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import KnowledgeConfig


def load_hooks(config: KnowledgeConfig) -> list[dict[str, Any]]:
    path = config.hook_config_file
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    hooks = data.get('hooks', [])
    if not isinstance(hooks, list):
        return []
    return [hook for hook in hooks if isinstance(hook, dict)]


def evaluate_source(config: KnowledgeConfig, relative_path: str) -> list[dict[str, Any]]:
    hooks = load_hooks(config)
    source_path = config.root / relative_path
    text = source_path.read_text(encoding='utf-8', errors='replace') if source_path.exists() else ''
    evaluations: list[dict[str, Any]] = []
    for hook in hooks:
        applies_to = [str(x) for x in hook.get('applies_to', []) or []]
        if applies_to and not _path_matches(relative_path, applies_to):
            continue
        eligibility = hook.get('eligibility', {}) if isinstance(hook.get('eligibility'), dict) else {}
        eligible = True
        reasons: list[str] = []
        for token in [str(x) for x in eligibility.get('reject_when_path_contains', []) or []]:
            if token and token in relative_path:
                eligible = False
                reasons.append(f'rejected_by_path:{token}')
        for token in [str(x) for x in eligibility.get('reject_when_content_contains', []) or []]:
            if token and token in text:
                eligible = False
                reasons.append(f'rejected_by_content:{token}')
        allow_tokens = [str(x) for x in eligibility.get('allow_when_content_contains_any', []) or []]
        if allow_tokens:
            if any(token and token in text for token in allow_tokens):
                reasons.append('allowed_by_content_marker')
            else:
                reasons.append('no_allow_marker_found')
        evaluations.append({'hook_id': hook.get('id'), 'kind': hook.get('kind'), 'eligible': eligible, 'action': hook.get('action'), 'reasons': reasons})
    return evaluations


def _path_matches(relative_path: str, patterns: list[str]) -> bool:
    path = Path(relative_path)
    return any(path.match(pattern) for pattern in patterns)
