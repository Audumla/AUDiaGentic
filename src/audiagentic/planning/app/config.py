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
        self.planning = self._read_required_yaml('planning.yaml')
        self.profiles = self._read_required_yaml('profiles.yaml')
        self.workflows = self._read_required_yaml('workflows.yaml')
        self.automations = self._read_required_yaml('automations.yaml')
        self.hooks = self._read_required_yaml('hooks.yaml')
        self.documentation = self._read_optional_yaml('documentation.yaml')
        # request_profiles is now merged into unified profiles (for backward compatibility)
        self.request_profiles = {"request_profiles": self.profiles.get("planning", {}).get("profiles", {})}
        self.profile_packs = self._read_profile_packs()

    def _read_required_yaml(self, filename: str) -> dict:
        return yaml.safe_load((self.config_dir / filename).read_text(encoding='utf-8'))

    def _read_optional_yaml(self, filename: str) -> dict:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}

    def _read_profile_packs(self) -> dict[str, dict]:
        profile_pack_dir = self.config_dir / 'profile-packs'
        if not profile_pack_dir.exists():
            return {}
        out: dict[str, dict] = {}
        for path in sorted(profile_pack_dir.glob('*.yaml')):
            out[path.stem] = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        return out

    def _validate_yaml_file(self, filename: str, schema: str, required: bool = True) -> list[str]:
        path = self.config_dir / filename
        if not path.exists():
            return [] if not required else [f'config {filename}: file is missing']
        inst = yaml.safe_load(path.read_text(encoding='utf-8'))
        sch = json.loads((self.schemas / schema).read_text(encoding='utf-8'))
        v = Draft202012Validator(sch)
        return [f'config {filename}: {e.message}' for e in v.iter_errors(inst)]

    def validate(self) -> list[str]:
        errors: list[str] = []
        for file, schema, required in [
            ('planning.yaml', 'planning-config.schema.json', True),
            ('profiles.yaml', 'profiles.schema.json', True),
            ('workflows.yaml', 'state-model.schema.json', True),
            ('automations.yaml', 'automations.schema.json', True),
            ('hooks.yaml', 'hooks-config.schema.json', True),
            ('documentation.yaml', 'documentation-config.schema.json', False),
            ('request-profiles.yaml', 'request-profiles.schema.json', False),
        ]:
            errors.extend(self._validate_yaml_file(file, schema, required=required))

        profile_pack_dir = self.config_dir / 'profile-packs'
        if profile_pack_dir.exists():
            schema = 'profile-pack.schema.json'
            for path in sorted(profile_pack_dir.glob('*.yaml')):
                sch = json.loads((self.schemas / schema).read_text(encoding='utf-8'))
                inst = yaml.safe_load(path.read_text(encoding='utf-8'))
                v = Draft202012Validator(sch)
                for e in v.iter_errors(inst):
                    errors.append(f'config profile-packs/{path.name}: {e.message}')
        return errors

    def workflow_for(self, kind: str, name: str | None = None) -> dict:
        group = self.workflows['planning']['workflows'][kind]
        wf_name = name or group['default']
        return group['named'][wf_name]

    def profile_for(self, name: str) -> dict:
        """Load a unified profile by name.

        Profiles combine request defaults (Understanding, Open Questions, suggested sections)
        and stack topology (on_request_create, allow_plan_overlay).

        Args:
            name: Profile name (e.g. 'feature', 'issue', 'direct', 'full')

        Returns:
            Profile dict with both request defaults and stack topology

        Raises:
            ValueError: If profile not found
        """
        profiles = (
            self.profiles.get("planning", {})
            .get("profiles", {})
        )
        if name not in profiles:
            raise ValueError(f"profile '{name}' not found")
        return profiles[name]

    def standard_defaults_for(self, kind: str) -> list[str]:
        """Get default standards for a planning kind.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'request')

        Returns:
            List of standard IDs to apply by default (e.g. ['standard-0006', 'standard-0005'])
        """
        defaults = (
            self.profiles.get("planning", {})
            .get("standard_defaults", {})
        )
        return defaults.get(kind, [])
