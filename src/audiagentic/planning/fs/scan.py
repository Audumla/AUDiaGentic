from __future__ import annotations
from pathlib import Path
from .repo import Repo

def scan_items(root: Path):
    return list(Repo(root).iter_docs())
