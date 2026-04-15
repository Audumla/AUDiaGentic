from __future__ import annotations

import json
from pathlib import Path

from ..fs.scan import scan_items
from .util import slugify


class Reconcile:
    def __init__(self, root: Path):
        self.root = root

    def run(self):
        items = scan_items(self.root)
        for item in items:
            if item.kind in {'request', 'task'}:
                desired_name = f"{item.data['id']}.md"
            else:
                desired_name = f"{item.data['id']}-{slugify(item.data['label'])}.md"
            desired = item.path.with_name(desired_name)
            if desired != item.path:
                desired.parent.mkdir(parents=True, exist_ok=True)
                item.path.rename(desired)
        ids = {i.data['id'] for i in items}
        attach_root = self.root / 'docs/planning/attachments'
        orphans = []
        if attach_root.exists():
            for p in attach_root.iterdir():
                if p.is_dir() and p.name not in ids:
                    orphans.append(p.name)
        out = self.root / '.audiagentic/planning/meta/orphans.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'orphans': orphans}, indent=2), encoding='utf-8')
        return {'orphans': orphans}
