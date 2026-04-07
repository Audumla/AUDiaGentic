from __future__ import annotations
import json
from pathlib import Path
from .util import now_iso
from ..fs.scan import scan_items
from .claims import Claims

class Indexer:
    def __init__(self, root: Path):
        self.root = root

    def write_indexes(self):
        items = scan_items(self.root)
        by_kind = {}
        for item in items:
            by_kind.setdefault(item.kind, []).append({
                'id': item.data['id'], 'label': item.data['label'], 'state': item.data['state'], 'path': str(item.path.relative_to(self.root))
            })
        idx_root = self.root / '.audiagentic/planning/indexes'
        idx_root.mkdir(parents=True, exist_ok=True)
        meta = {'convention_version': 1, 'generated_at': now_iso()}
        names = {'request': 'requests', 'spec': 'specifications', 'plan': 'plans', 'task': 'tasks', 'wp': 'work-packages', 'standard': 'standards'}
        for kind, name in names.items():
            payload = {**meta, 'items': by_kind.get(kind, [])}
            (idx_root / f'{name}.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
        trace = {**meta, 'refs': []}
        for item in items:
            for field in ['request_refs', 'spec_refs', 'standard_refs']:
                for r in item.data.get(field, []) or []:
                    trace['refs'].append({'src': item.data['id'], 'dst': r, 'field': field})
            for field in ['plan_ref', 'spec_ref', 'parent_task_ref']:
                if item.data.get(field):
                    trace['refs'].append({'src': item.data['id'], 'dst': item.data[field], 'field': field})
            for field in ['task_refs', 'work_package_refs']:
                for rel in item.data.get(field, []) or []:
                    trace['refs'].append({'src': item.data['id'], 'dst': rel['ref'], 'field': field, 'seq': rel.get('seq'), 'display': rel.get('display')})
        (idx_root / 'trace.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
        claims = Claims(self.root / '.audiagentic/planning/claims/claims.json').load()['claims']
        claimed = {c['id']: c for c in claims}
        readiness = {**meta, 'items': []}
        for item in items:
            readiness['items'].append({'id': item.data['id'], 'kind': item.kind, 'state': item.data['state'], 'claimed': item.data['id'] in claimed})
        (idx_root / 'readiness.json').write_text(json.dumps(readiness, indent=2), encoding='utf-8')
        (idx_root / 'claims.json').write_text(json.dumps({**meta, 'claims': claims}, indent=2), encoding='utf-8')
        # Preserve dispatch registry if it exists; do not overwrite (it is append-only via hook)
        dispatch_path = idx_root / 'dispatch.json'
        if not dispatch_path.exists():
            dispatch_path.write_text(json.dumps({**meta, 'entries': []}, indent=2), encoding='utf-8')
