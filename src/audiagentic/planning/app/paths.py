from __future__ import annotations
import yaml
from pathlib import Path
from ..domain.states import KIND_MAP

class Paths:
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = root / '.audiagentic' / 'planning' / 'config'
        self.planning_cfg = yaml.safe_load((self.config_dir / 'planning.yaml').read_text(encoding='utf-8'))
        self.dirs = self.planning_cfg['planning']['dirs']

    def kind_dir(self, kind: str, domain: str | None = None) -> Path:
        kind = KIND_MAP.get(kind, kind)
        mapping = {
            'request': self.dirs['requests'],
            'spec': self.dirs['specifications'],
            'plan': self.dirs['plans'],
            'task': self.dirs['tasks'],
            'wp': self.dirs['work_packages'],
            'standard': self.dirs['standards'],
        }
        p = self.root / mapping[kind]
        if kind in {'task', 'wp'} and domain:
            p = p / domain
        return p

    def support_dir(self, name: str) -> Path:
        return self.root / self.dirs[name]
