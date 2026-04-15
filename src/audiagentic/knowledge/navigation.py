from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .config import KnowledgeConfig
from .markdown_io import load_page_by_id
from .registry import load_action_registry
from .search import search_pages
from .utils import load_yaml_file


def load_navigation_routes(config: KnowledgeConfig) -> dict[str, Any]:
    data = load_yaml_file(config.navigation_config_file, {'routes': [], 'fallbacks': []})
    if not isinstance(data, dict):
        return {'routes': [], 'fallbacks': []}
    data.setdefault('routes', [])
    data.setdefault('fallbacks', [])
    return data


def suggest_navigation(config: KnowledgeConfig, goal: str, *, context: dict[str, Any] | None = None, limit: int = 5) -> dict[str, Any]:
    context = context or {}
    nav = load_navigation_routes(config)
    goal_lower = goal.lower()
    route_hits: list[dict[str, Any]] = []
    for route in nav.get('routes', []):
        if not isinstance(route, dict):
            continue
        keywords = [str(x).lower() for x in route.get('keywords', []) or []]
        score = sum(1 for kw in keywords if kw and kw in goal_lower)
        if score <= 0:
            continue
        pages = []
        for page_id in [str(x) for x in route.get('page_ids', []) or []]:
            page = load_page_by_id(config.pages_root, config.meta_root, page_id)
            if page:
                pages.append({'page_id': page.page_id, 'title': page.title, 'path': str(page.content_path.relative_to(config.root))})
        route_hits.append({
            'route_id': route.get('id'),
            'label': route.get('label'),
            'score': score,
            'pages': pages,
            'deterministic_actions': [str(x) for x in route.get('deterministic_actions', []) or []],
            'note': route.get('note'),
        })
    route_hits.sort(key=lambda item: item['score'], reverse=True)
    search_hits = [asdict(item) for item in search_pages(config, goal, limit=limit)]
    action_registry = load_action_registry(config)
    fallback_actions = []
    for fallback in nav.get('fallbacks', []):
        if not isinstance(fallback, dict):
            continue
        keywords = [str(x).lower() for x in fallback.get('keywords', []) or []]
        if keywords and not any(kw in goal_lower for kw in keywords):
            continue
        action_id = str(fallback.get('action_id', '')).strip()
        if action_id and action_id in action_registry:
            fallback_actions.append({'action_id': action_id, 'label': fallback.get('label'), 'note': fallback.get('note')})
    return {
        'goal': goal,
        'matched_routes': route_hits[:limit],
        'search_hits': search_hits,
        'fallback_actions': fallback_actions,
    }


def explain_navigation_contract(config: KnowledgeConfig) -> dict[str, Any]:
    nav = load_navigation_routes(config)
    actions = load_action_registry(config)
    return {
        'navigation_config': str(config.navigation_config_file.relative_to(config.root)),
        'route_count': len(nav.get('routes', [])),
        'fallback_count': len(nav.get('fallbacks', [])),
        'deterministic_actions': sorted(actions.keys()),
    }
