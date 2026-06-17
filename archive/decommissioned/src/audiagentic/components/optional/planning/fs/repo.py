from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..app.config import Config
from ..domain.models import Item
from .read import parse_markdown


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self.config = Config(root)

    def iter_docs(self) -> Iterable[Item]:
        base_dir = self.config.dir_path("base")
        docs_root = self.root / Path(base_dir)
        if not docs_root.exists():
            return
        attachments_dir = self.config.attachments_dir()
        attachments_parts = tuple(Path(attachments_dir).parts)
        for path in sorted(docs_root.rglob('*.md')):
            if 'templates' in path.parts:
                continue
            rel_parts = path.relative_to(self.root).parts
            if attachments_parts and rel_parts[: len(attachments_parts)] == attachments_parts:
                continue
            data, body = parse_markdown(path)
            kind = self.kind_from_id(data.get('id', ''))
            if not kind:
                continue
            yield Item(kind=kind, path=path, data=data, body=body)

    def kind_from_id(self, id_: str) -> str | None:
        if not id_:
            return None
        prefix = id_.split('-', 1)[0]
        if prefix in set(self.config.all_kinds()):
            return prefix
        return None
