from __future__ import annotations
import re
import yaml
from pathlib import Path
from typing import Tuple

FM_RE = re.compile(r'^---\n(.*?)\n---\n?(.*)$', re.S)


def parse_markdown(path: Path) -> Tuple[dict, str]:
    text = path.read_text(encoding='utf-8')
    m = FM_RE.match(text)
    if not m:
        raise ValueError(f'missing frontmatter: {path}')
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    return fm, body
