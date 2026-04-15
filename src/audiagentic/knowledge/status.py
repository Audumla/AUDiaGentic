from __future__ import annotations

from collections import Counter

from .config import KnowledgeConfig
from .events import scan_events
from .markdown_io import load_pages
from .sync import scan_drift
from .validation import validate_vault


def build_status(config: KnowledgeConfig) -> dict:
    pages = load_pages(config.pages_root, config.meta_root)
    issues = validate_vault(config)
    drift = scan_drift(config)
    events = scan_events(config)
    type_counts = Counter(page.page_type for page in pages)
    return {'page_count': len(pages), 'page_types': dict(sorted(type_counts.items())), 'issues': {'errors': len([i for i in issues if i.severity == 'error']), 'warnings': len([i for i in issues if i.severity == 'warning'])}, 'drift': {'stale_pages': len({item.page_id for item in drift if item.status != 'ok'}), 'changed_sources': len([item for item in drift if item.status == 'changed']), 'missing_sources': len([item for item in drift if item.status == 'missing']), 'untracked_sources': len([item for item in drift if item.status == 'untracked'])}, 'events': {'pending': len(events), 'affected_pages': sorted({page_id for event in events for page_id in event.affected_pages})}}
