from __future__ import annotations
import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

# Schemas are bundled with the audiagentic package, not in the project root.
# From app/config.py: parents[2] = src/audiagentic/
_PLANNING_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "planning"


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = root / '.audiagentic' / 'planning' / 'config'
        self.schemas = _PLANNING_SCHEMA_DIR
        self.planning = yaml.safe_load((self.config_dir / 'planning.yaml').read_text(encoding='utf-8'))
        self.profiles = yaml.safe_load((self.config_dir / 'profiles.yaml').read_text(encoding='utf-8'))
        self.workflows = yaml.safe_load((self.config_dir / 'workflows.yaml').read_text(encoding='utf-8'))
        self.automations = yaml.safe_load((self.config_dir / 'automations.yaml').read_text(encoding='utf-8'))
        self.hooks = yaml.safe_load((self.config_dir / 'hooks.yaml').read_text(encoding='utf-8'))

    def validate(self) -> list[str]:
        errors: list[str] = []
        for file, schema in [
            ('planning.yaml', 'planning-config.schema.json'),
            ('profiles.yaml', 'profiles.schema.json'),
            ('workflows.yaml', 'state-model.schema.json'),
            ('automations.yaml', 'automations.schema.json'),
            ('hooks.yaml', 'hooks-config.schema.json'),
        ]:
            inst = yaml.safe_load((self.config_dir / file).read_text(encoding='utf-8'))
            sch = json.loads((self.schemas / schema).read_text(encoding='utf-8'))
            v = Draft202012Validator(sch)
            for e in v.iter_errors(inst):
                errors.append(f'config {file}: {e.message}')
        return errors

    def workflow_for(self, kind: str, name: str | None = None) -> dict:
        group = self.workflows['planning']['workflows'][kind]
        wf_name = name or group['default']
        return group['named'][wf_name]
