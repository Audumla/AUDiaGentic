from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..domain.models import Item
from .read import parse_markdown


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def iter_docs(self) -> Iterable[Item]:
        docs_root = self.root / 'docs' / 'planning'
        if not docs_root.exists():
            return
        for path in sorted(docs_root.rglob('*.md')):
            if 'attachments' in path.parts or 'templates' in path.parts:
                continue
            data, body = parse_markdown(path)
            kind = self.kind_from_id(data.get('id', ''))
            if not kind:
                continue
            yield Item(kind=kind, path=path, data=data, body=body)

    @staticmethod
    def kind_from_id(id_: str) -> str | None:
        if not id_:
            return None
        prefix = id_.split('-', 1)[0]
        if prefix in {'request', 'spec', 'plan', 'task', 'wp', 'standard'}:
            return prefix
        return None
