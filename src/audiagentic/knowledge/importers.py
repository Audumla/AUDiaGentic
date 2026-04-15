from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .config import KnowledgeConfig
from .markdown_io import load_page_by_id, save_page, sidecar_for_page
from .models import ImportResult, KnowledgePage, Section
from .registry import load_importer_registry, resolve_registry_handler
from .sync import record_sync_state
from .utils import today_utc_iso


def scaffold_page(
    config: KnowledgeConfig,
    *,
    page_id: str,
    title: str,
    page_type: str,
    summary: str,
    owners: list[str],
    tags: list[str] | None = None,
    related: list[str] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    update_existing: bool = False,
) -> ImportResult:
    page_dir = config.page_type_dirs.get(page_type, page_type or 'misc')
    filename = f'{page_id}.md'
    content_path = config.pages_root / page_dir / filename
    meta_path = sidecar_for_page(config.pages_root, config.meta_root, content_path)
    existing = content_path.exists() or meta_path.exists()
    if existing and not update_existing:
        return ImportResult('skipped', page_id, str(content_path.relative_to(config.root)), str(meta_path.relative_to(config.root)), '', 'scaffold', 'Page already exists')
    sections = [Section(title=section, body=_default_section_body(section, title)) for section in config.scaffold_default_sections]
    metadata = {
        'id': page_id,
        'title': title,
        'type': page_type,
        'status': 'active',
        'summary': summary,
        'owners': owners,
        'tags': tags or [],
        'related': related or [],
        'updated_at': today_utc_iso(),
        'source_refs': source_refs or [],
    }
    save_page(KnowledgePage(content_path, meta_path, metadata, sections, ''))
    return ImportResult('updated' if existing else 'created', page_id, str(content_path.relative_to(config.root)), str(meta_path.relative_to(config.root)), '', 'scaffold', 'Scaffolded page')


def seed_from_manifest(config: KnowledgeConfig, manifest_path: Path, *, record_sync: bool = False, update_existing: bool = False) -> list[ImportResult]:
    import yaml

    data = yaml.safe_load(manifest_path.read_text(encoding='utf-8')) or {}
    items = data.get('items', []) if isinstance(data, dict) else []
    results: list[ImportResult] = []
    touched_page_ids: list[str] = []
    registry = load_importer_registry(config)
    for item in items:
        if not isinstance(item, dict):
            continue
        source_rel = str(item.get('source_path', '')).strip()
        source_path = config.root / source_rel
        if not source_rel or not source_path.exists():
            results.append(ImportResult('skipped', str(item.get('page_id', '')), '', '', source_rel, str(item.get('strategy', 'unknown')), 'Missing source file'))
            continue
        strategy = str(item.get('strategy', 'markdown_doc'))
        page_id = str(item.get('page_id') or _derive_page_id(source_rel, str(item.get('page_type', 'system'))))
        title = str(item.get('title') or _derive_title(source_path))
        page_type = str(item.get('page_type', 'system'))
        page_dir = config.page_type_dirs.get(page_type, page_type or 'misc')
        content_path = config.pages_root / page_dir / f'{page_id}.md'
        meta_path = sidecar_for_page(config.pages_root, config.meta_root, content_path)
        existing = load_page_by_id(config.pages_root, config.meta_root, page_id)
        if existing and not update_existing:
            results.append(ImportResult('skipped', page_id, str(existing.content_path.relative_to(config.root)), str(existing.meta_path.relative_to(config.root)), source_rel, strategy, 'Page already exists'))
            continue
        handler, defaults = resolve_registry_handler(registry, strategy)
        payload = handler(config=config, item={**defaults, **item}, source_path=source_path)
        sections = payload['sections']
        summary = str(payload['summary'])
        extra_tags = list(payload.get('extra_tags', []))
        metadata = {
            'id': page_id,
            'title': title,
            'type': page_type,
            'status': str(item.get('status', defaults.get('status', 'active'))),
            'summary': str(item.get('summary') or summary),
            'owners': item.get('owners') or defaults.get('owners') or ['core'],
            'tags': _dedupe_list(list(item.get('tags') or []) + extra_tags),
            'related': item.get('related') or defaults.get('related') or [],
            'updated_at': str(item.get('updated_at') or defaults.get('updated_at') or today_utc_iso()),
            'source_refs': item.get('source_refs') or defaults.get('source_refs') or [{'path': source_rel, 'kind': str(item.get('source_kind', defaults.get('source_kind', 'repo_doc')))}],
        }
        save_page(KnowledgePage(content_path, meta_path, metadata, sections, ''))
        results.append(ImportResult('updated' if existing else 'created', page_id, str(content_path.relative_to(config.root)), str(meta_path.relative_to(config.root)), source_rel, strategy, 'Seeded from manifest'))
        touched_page_ids.append(page_id)
    if record_sync and touched_page_ids:
        record_sync_state(config, touched_page_ids)
    return results


def import_markdown_doc(*, config: KnowledgeConfig, item: dict[str, Any], source_path: Path) -> dict[str, Any]:
    heading = _derive_title(source_path)
    text = source_path.read_text(encoding='utf-8', errors='replace')
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip() and not p.strip().startswith('#')]
    excerpt = paragraphs[0] if paragraphs else f'Source file `{source_path.name}` imported for current-state knowledge review.'
    summary = f'Current-state summary of {heading}.'
    return {
        'sections': [
            Section('Summary', summary),
            Section('Current state', excerpt),
            Section('How to use', f'Review the underlying source at `{source_path.as_posix()}` for full detail and update this page with durable current-state guidance.'),
            Section('Sync notes', f'Source file: `{source_path.as_posix()}`\n\nThis page was seeded from source material and should stay concise and current-state focused.'),
            Section('References', f'- Source: `{source_path.as_posix()}`'),
        ],
        'summary': summary,
        'extra_tags': ['imported'],
    }


def import_yaml_config(*, config: KnowledgeConfig, item: dict[str, Any], source_path: Path) -> dict[str, Any]:
    import yaml

    text = source_path.read_text(encoding='utf-8', errors='replace')
    data = yaml.safe_load(text) or {}
    keys = sorted(str(k) for k in data.keys()) if isinstance(data, dict) else []
    summary = f'Current-state summary of {source_path.name} and its main configuration surfaces.'
    return {
        'sections': [
            Section('Summary', summary),
            Section('Current state', f"This config currently exposes these top-level keys: {', '.join(keys) if keys else '(none detected)'}."),
            Section('How to use', 'Use this page to understand the current configuration surface and where it feeds downstream behavior.'),
            Section('Sync notes', f'Source file: `{source_path.as_posix()}`\n\nRegenerate or patch this page when canonical keys or aliases materially change.'),
            Section('References', f'- Source: `{source_path.as_posix()}`'),
        ],
        'summary': summary,
        'extra_tags': ['config', 'imported'],
    }


def import_ndjson_events(*, config: KnowledgeConfig, item: dict[str, Any], source_path: Path) -> dict[str, Any]:
    text = source_path.read_text(encoding='utf-8', errors='replace')
    lines = [line for line in text.splitlines() if line.strip()]
    event_types = Counter()
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        event_type = str(payload.get('event_type') or payload.get('type') or 'unknown')
        event_types[event_type] += 1
    summary = f'Current-state summary of runtime event artifacts in {source_path.name}.'
    current = 'Observed event types: ' + ', '.join(f'{k}({v})' for k, v in event_types.items()) if event_types else 'No parsable events were detected.'
    return {
        'sections': [
            Section('Summary', summary),
            Section('Current state', current),
            Section('How to use', 'Use this page to document what these runtime events mean now and which downstream systems depend on them.'),
            Section('Sync notes', f'Source file: `{source_path.as_posix()}`\n\nRefresh this page when emitted event families or payload expectations materially change.'),
            Section('References', f'- Source: `{source_path.as_posix()}`'),
        ],
        'summary': summary,
        'extra_tags': ['runtime', 'events', 'imported'],
    }


def import_json_snapshot(*, config: KnowledgeConfig, item: dict[str, Any], source_path: Path) -> dict[str, Any]:
    text = source_path.read_text(encoding='utf-8', errors='replace')
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    keys = sorted(str(k) for k in data.keys()) if isinstance(data, dict) else []
    summary = f'Current-state summary of JSON snapshot {source_path.name}.'
    return {
        'sections': [
            Section('Summary', summary),
            Section('Current state', f"Top-level keys present: {', '.join(keys) if keys else '(none detected)'}."),
            Section('How to use', 'Use this page to explain what this JSON snapshot represents now and which downstream workflows depend on it.'),
            Section('Sync notes', f'Source file: `{source_path.as_posix()}`\n\nRefresh when the snapshot schema or semantics change.'),
            Section('References', f'- Source: `{source_path.as_posix()}`'),
        ],
        'summary': summary,
        'extra_tags': ['json', 'snapshot', 'imported'],
    }


def _derive_page_id(source_rel: str, page_type: str) -> str:
    stem = Path(source_rel).stem.lower()
    stem = re.sub(r'[^a-z0-9]+', '-', stem).strip('-')
    return f'know-{page_type}-{stem}'


def _derive_title(source_path: Path) -> str:
    text = source_path.read_text(encoding='utf-8', errors='replace')
    for line in text.splitlines():
        if line.startswith('# '):
            return line[2:].strip()
    return source_path.stem.replace('_', ' ').replace('-', ' ').title()


def _default_section_body(section: str, title: str) -> str:
    mapping = {
        'Summary': f'Current-state summary of {title}.',
        'Current state': 'Describe how this works now.',
        'How to use': 'Describe how a human or agent should use this now.',
        'Sync notes': 'Record how this page should be refreshed and what sources it follows.',
        'References': '- Add supporting references here.',
    }
    return mapping.get(section, f'Add {section.lower()} content here.')


def _dedupe_list(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
