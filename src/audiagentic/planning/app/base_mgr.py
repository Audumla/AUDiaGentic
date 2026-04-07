from __future__ import annotations
from pathlib import Path
from .paths import Paths
from .util import slugify

class BaseMgr:
    def __init__(self, root: Path):
        self.root = root
        self.paths = Paths(root)

    def path_for(self, kind: str, id_: str, label: str, domain: str | None = None):
        d = self.paths.kind_dir(kind, domain)
        if kind in {'request', 'task'}:
            return d / f'{id_}.md'
        return d / f'{id_}-{slugify(label)}.md'
