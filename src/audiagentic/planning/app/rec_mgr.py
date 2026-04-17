from __future__ import annotations

import json
from pathlib import Path

from ..fs.scan import scan_items
from .paths import Paths


class Reconcile:
    def __init__(self, root: Path):
        self.root = root
        self.paths = Paths(root)

    def run(self):
        """Reconcile planning filenames to canonical pattern and report changes.

        Returns:
            Dict with 'renames' (list of {id, from, to}) and 'orphans' (attachment dirs with no item).
        """
        items = scan_items(self.root)
        renames = []
        for item in items:
            desired_name = self.paths.filename_for(item.kind, item.data["id"], item.data["label"])
            desired = item.path.with_name(desired_name)
            if desired != item.path:
                desired.parent.mkdir(parents=True, exist_ok=True)
                item.path.rename(desired)
                renames.append({
                    "id": item.data["id"],
                    "from": item.path.name,
                    "to": desired_name,
                })
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
        return {'renames': renames, 'orphans': orphans}
