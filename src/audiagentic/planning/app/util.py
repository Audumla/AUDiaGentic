from __future__ import annotations
import re
from datetime import datetime, timezone

def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-') or 'item'

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def body_has_section(body: str, section: str) -> bool:
    return f'# {section}' in body or f'## {section}' in body
