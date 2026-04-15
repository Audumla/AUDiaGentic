from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import KnowledgeConfig
from .markdown_io import load_page, load_page_by_id, save_page, sidecar_for_page
from .models import KnowledgePage, PatchResult, Section


class PatchError(Exception):
    pass


def apply_patch_file(config: KnowledgeConfig, patch_path: Path) -> PatchResult:
    data = yaml.safe_load(patch_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise PatchError(f'Patch file {patch_path} must contain a mapping')
    target_id = data.get('target_page_id')
    target_path = data.get('target_path')
    actions = data.get('actions', [])
    if not isinstance(actions, list) or not actions:
        raise PatchError('Patch must include at least one action')
    if target_id:
        page = _find_page_by_id(config, str(target_id))
    elif target_path:
        content_path = config.root / str(target_path)
        meta_path = sidecar_for_page(config.pages_root, config.meta_root, content_path)
        if not meta_path.exists():
            raise PatchError(f'Missing sidecar for target path {target_path}')
        page = load_page(content_path, meta_path)
    else:
        raise PatchError('Patch must provide target_page_id or target_path')
    applied: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            raise PatchError('Each action must be a mapping')
        action_name = str(action.get('action', '')).strip()
        if not action_name:
            raise PatchError('Action missing action name')
        _apply_action(config, page, action_name, action)
        applied.append(action_name)
    save_page(page)
    return PatchResult(changed=True, path=str(page.content_path.relative_to(config.root)), actions_applied=applied, message='Patch applied')


def _find_page_by_id(config: KnowledgeConfig, page_id: str) -> KnowledgePage:
    page = load_page_by_id(config.pages_root, config.meta_root, page_id)
    if page is None:
        raise PatchError(f"Target page id '{page_id}' not found")
    return page


def _apply_action(config: KnowledgeConfig, page: KnowledgePage, action_name: str, action: dict[str, Any]) -> None:
    if action_name == 'set_metadata':
        page.metadata[str(action['field'])] = action.get('value')
        return
    if action_name == 'add_list_item':
        field = str(action['field'])
        value = action.get('value')
        current = page.metadata.get(field) or []
        if not isinstance(current, list):
            raise PatchError(f"Metadata field '{field}' is not a list")
        if value not in current:
            current.append(value)
        page.metadata[field] = current
        return
    if action_name == 'remove_list_item':
        field = str(action['field'])
        value = action.get('value')
        current = page.metadata.get(field) or []
        if not isinstance(current, list):
            raise PatchError(f"Metadata field '{field}' is not a list")
        page.metadata[field] = [item for item in current if item != value]
        return
    if action_name == 'replace_section':
        _replace_section(page, str(action['section']), str(action.get('body', '')).strip())
        return
    if action_name == 'append_section':
        _append_section(page, str(action['section']), str(action.get('body', '')).strip())
        return
    if action_name == 'create_page':
        _create_page(config, action)
        return
    raise PatchError(f"Unsupported action '{action_name}'")


def _replace_section(page: KnowledgePage, section_title: str, body: str) -> None:
    for idx, section in enumerate(page.sections):
        if section.title == section_title:
            page.sections[idx] = Section(title=section_title, body=body)
            return
    page.sections.append(Section(title=section_title, body=body))


def _append_section(page: KnowledgePage, section_title: str, body: str) -> None:
    for idx, section in enumerate(page.sections):
        if section.title == section_title:
            page.sections[idx] = Section(title=section.title, body=(section.body.rstrip() + '\n\n' + body).strip())
            return
    page.sections.append(Section(title=section_title, body=body))


def _create_page(config: KnowledgeConfig, action: dict[str, Any]) -> None:
    metadata = action.get('metadata')
    sections = action.get('sections')
    if not isinstance(metadata, dict) or not isinstance(sections, list):
        raise PatchError('create_page requires metadata mapping and sections list')
    page_type = str(metadata.get('type', ''))
    page_dir = config.page_type_dirs.get(page_type, page_type or 'misc')
    filename = str(action.get('filename') or metadata.get('id') or 'new-page')
    if not filename.endswith('.md'):
        filename += '.md'
    content_path = config.pages_root / page_dir / filename
    meta_path = sidecar_for_page(config.pages_root, config.meta_root, content_path)
    if content_path.exists() or meta_path.exists():
        raise PatchError(f'Page already exists: {content_path}')
    page_sections = [Section(title=str(s['title']), body=str(s.get('body', '')).strip()) for s in sections]
    save_page(KnowledgePage(content_path, meta_path, {str(k): v for k, v in metadata.items()}, page_sections, ''))
