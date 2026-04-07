from __future__ import annotations
import yaml
from pathlib import Path


def dump_markdown(path: Path, data: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{fm}\n---\n\n{body.rstrip()}\n", encoding='utf-8')
