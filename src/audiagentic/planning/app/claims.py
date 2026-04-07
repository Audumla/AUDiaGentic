from __future__ import annotations
import json
from pathlib import Path
from .util import now_iso

class Claims:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({'claims': []}, indent=2), encoding='utf-8')

    def load(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def save(self, data):
        self.path.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        data = self.load()
        data['claims'] = [c for c in data['claims'] if c['id'] != id_]
        rec = {'kind': kind, 'id': id_, 'holder': holder, 'claimed_at': now_iso(), 'ttl': ttl}
        data['claims'].append(rec)
        self.save(data)
        return rec

    def unclaim(self, id_: str):
        data = self.load()
        before = len(data['claims'])
        data['claims'] = [c for c in data['claims'] if c['id'] != id_]
        self.save(data)
        return before != len(data['claims'])
