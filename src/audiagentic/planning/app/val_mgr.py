from __future__ import annotations
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from ..fs.scan import scan_items
from .config import Config, _PLANNING_SCHEMA_DIR
from .util import body_has_section

REQ_SECTIONS = {
    'request': ['Understanding', 'Source Refs', 'Open Questions', 'Notes'],
    'spec': ['Purpose', 'Scope', 'Requirements', 'Constraints', 'Acceptance Criteria'],
    'plan': ['Objectives', 'Delivery Approach', 'Dependencies'],
    'wp': ['Objective', 'Scope of This Package', 'Inputs', 'Instructions', 'Required Outputs', 'Acceptance Checks', 'Non-Goals'],
    'task': ['Description'],
}

class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.schemas = _PLANNING_SCHEMA_DIR
        self.config = Config(root)

    def validate_all(self) -> list[str]:
        errors = []
        errors.extend(self.config.validate())
        items = scan_items(self.root)
        ids = set()
        for item in items:
            if item.data['id'] in ids:
                errors.append(f'duplicate id: {item.data["id"]}')
            ids.add(item.data['id'])
            schema_name = {
                'request': 'request.schema.json',
                'spec': 'specification.schema.json',
                'plan': 'plan.schema.json',
                'task': 'task.schema.json',
                'wp': 'work-package.schema.json',
                'standard': None,
            }[item.kind]
            sch = None
            if schema_name:
                sch = json.loads((self.schemas / schema_name).read_text(encoding='utf-8'))
                v = Draft202012Validator(sch)
                for e in v.iter_errors(item.data):
                    errors.append(f'{item.path}: {e.message}')
            allowed = set((sch.get('properties', {}) if sch else {}).keys()) if sch else set(item.data.keys())
            for k in item.data.keys():
                if sch and k not in allowed:
                    errors.append(f"{item.path}: forbidden top-level field '{k}', use meta")
            if item.kind in {'request', 'task'}:
                if item.path.name != f'{item.data["id"]}.md':
                    errors.append(f"{item.path}: filename must be {item.data['id']}.md")
            elif item.kind in {'spec', 'plan', 'wp', 'standard'}:
                if not item.path.name.startswith(item.data['id']):
                    errors.append(f"{item.path}: filename must start with {item.data['id']}")
            for sec in REQ_SECTIONS.get(item.kind, []):
                if not body_has_section(item.body, sec):
                    errors.append(f"{item.path}: missing section '{sec}'")
            if item.kind == 'task':
                if item.path.parent.parent.name != 'tasks':
                    errors.append(f"{item.path}: task must be under docs/planning/tasks/<domain>/")
            if item.kind == 'wp':
                if item.path.parent.parent.name != 'work-packages':
                    errors.append(f"{item.path}: wp must be under docs/planning/work-packages/<domain>/")
        return errors
