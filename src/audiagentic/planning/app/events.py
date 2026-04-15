from __future__ import annotations

import json
from pathlib import Path

from .util import now_iso


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: dict):
        rec = {'ts': now_iso(), 'event': event, **payload}
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
