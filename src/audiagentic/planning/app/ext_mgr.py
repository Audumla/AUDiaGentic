from __future__ import annotations
import json, yaml
from pathlib import Path
from ..fs.scan import scan_items
from .standards import effective_standard_refs
from .api_types import ItemView

class Extracts:
    def __init__(self, root: Path):
        self.root = root

    def show(self, id_: str) -> dict:
        items = {i.data['id']: ItemView(i.kind, i.path, i.data, i.body) for i in scan_items(self.root)}
        item = items[id_]
        out = dict(item.data)
        out['kind'] = item.kind
        out['path'] = str(item.path.relative_to(self.root))
        return out

    def extract(self, id_: str, with_related: bool = False, with_resources: bool = False) -> dict:
        items = {i.data['id']: ItemView(i.kind, i.path, i.data, i.body) for i in scan_items(self.root)}
        item = items[id_]
        out = {'item': self.show(id_), 'body': item.body, 'effective_standard_refs': effective_standard_refs(item, items)}
        if with_related:
            rel = {}
            for field in ['request_refs', 'spec_refs', 'task_refs', 'work_package_refs', 'plan_ref', 'spec_ref', 'parent_task_ref']:
                if field in item.data:
                    rel[field] = item.data[field]
            out['related'] = rel
        if with_resources:
            attach_dir = self.root / 'docs/planning/attachments' / id_
            if attach_dir.exists():
                out['attachments'] = [str(p.relative_to(self.root)) for p in sorted(attach_dir.rglob('*')) if p.is_file()]
        ep = self.root / '.audiagentic/planning/extracts' / f'{id_}.json'
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text(json.dumps(out, indent=2), encoding='utf-8')
        return out

    def owner(self, path_fragment: str) -> list[dict]:
        owners = []
        attach_root = self.root / 'docs/planning/attachments'
        if not attach_root.exists():
            return owners
        for amap in sorted(attach_root.glob('*/resource-map.yaml')):
            data = yaml.safe_load(amap.read_text(encoding='utf-8')) or {}
            for key in ['owned', 'related', 'tests', 'schemas']:
                for p in data.get(key, []) or []:
                    if path_fragment in p:
                        owners.append({'owner': data.get('owner'), 'type': key, 'path': p})
        return owners
