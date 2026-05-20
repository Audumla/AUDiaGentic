from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

import yaml


def normalize_text(path: Path, text: str) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in {'.yml', '.yaml'}:
            data = yaml.safe_load(text)
            return yaml.safe_dump(data, sort_keys=True, allow_unicode=True, width=100, default_flow_style=False)
        if suffix == '.json':
            data = json.loads(text)
            return json.dumps(data, indent=2, sort_keys=True) + '\n'
    except Exception:
        return text
    return text


def unified_diff_excerpt(old_text: str | None, new_text: str | None, path_label: str, context_lines: int = 2, max_lines: int = 80) -> str:
    old_lines = (old_text or '').splitlines()
    new_lines = (new_text or '').splitlines()
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=f'a/{path_label}', tofile=f'b/{path_label}', lineterm='', n=context_lines))
    if not diff_lines:
        return ''
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines] + [f'... diff truncated after {max_lines} lines ...']
    return '\n'.join(diff_lines)


def summarize_structured_change(path: Path, old_text: str | None, new_text: str | None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {'.yml', '.yaml'}:
        return _summarize_mapping_change(_safe_yaml(old_text), _safe_yaml(new_text))
    if suffix == '.json':
        return _summarize_mapping_change(_safe_json(old_text), _safe_json(new_text))
    if suffix == '.md':
        return _summarize_markdown_change(old_text or '', new_text or '')
    return {}


def _safe_yaml(text: str | None) -> Any:
    try:
        return yaml.safe_load(text or '')
    except Exception:
        return None


def _safe_json(text: str | None) -> Any:
    try:
        return json.loads(text or '')
    except Exception:
        return None


def _summarize_mapping_change(before: Any, after: Any) -> dict[str, Any]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {}
    before_keys = set(str(k) for k in before.keys())
    after_keys = set(str(k) for k in after.keys())
    changed = [key for key in sorted(before_keys & after_keys) if before.get(key) != after.get(key)]
    return {'added_keys': sorted(after_keys - before_keys), 'removed_keys': sorted(before_keys - after_keys), 'changed_keys': changed}


def _summarize_markdown_change(before: str, after: str) -> dict[str, Any]:
    def headings(text: str) -> list[str]:
        return [line[3:].strip() for line in text.splitlines() if line.startswith('## ')]
    b = headings(before)
    a = headings(after)
    return {'headings_before': b, 'headings_after': a, 'added_headings': [h for h in a if h not in b], 'removed_headings': [h for h in b if h not in a]}
