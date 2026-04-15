from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Schemas are bundled with the audiagentic package, not in the project root.
# From app/config.py: parents[2] = src/audiagentic/
_PLANNING_SCHEMA_DIR = (
    Path(__file__).resolve().parents[2] / "foundation" / "contracts" / "schemas" / "planning"
)


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.config_dir = root / ".audiagentic" / "planning" / "config"
        self.schemas = _PLANNING_SCHEMA_DIR
        self.planning = self._read_required_yaml("planning.yaml")
        self.profiles = self._read_required_yaml("profiles.yaml")
        self.workflows = self._read_required_yaml("workflows.yaml")
        self.automations = self._read_required_yaml("automations.yaml")
        self.documentation = self._read_optional_yaml("documentation.yaml")
        # request_profiles is now merged into unified profiles (for backward compatibility)
        self.request_profiles = {
            "request_profiles": self.profiles.get("planning", {}).get("profiles", {})
        }
        self.profile_packs = self._read_profile_packs()

    def _read_required_yaml(self, filename: str) -> dict:
        return yaml.safe_load((self.config_dir / filename).read_text(encoding="utf-8"))

    def _read_optional_yaml(self, filename: str) -> dict:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _read_profile_packs(self) -> dict[str, dict]:
        profile_pack_dir = self.config_dir / "profile-packs"
        if not profile_pack_dir.exists():
            return {}
        out: dict[str, dict] = {}
        for path in sorted(profile_pack_dir.glob("*.yaml")):
            out[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return out

    def _validate_yaml_file(self, filename: str, schema: str, required: bool = True) -> list[str]:
        path = self.config_dir / filename
        if not path.exists():
            return [] if not required else [f"config {filename}: file is missing"]
        inst = yaml.safe_load(path.read_text(encoding="utf-8"))
        sch = json.loads((self.schemas / schema).read_text(encoding="utf-8"))
        v = Draft202012Validator(sch)
        return [f"config {filename}: {e.message}" for e in v.iter_errors(inst)]

    def validate(self) -> list[str]:
        errors: list[str] = []
        for file, schema, required in [
            ("planning.yaml", "planning-config.schema.json", True),
            ("profiles.yaml", "profiles.schema.json", True),
            ("workflows.yaml", "state-model.schema.json", True),
            ("automations.yaml", "automations.schema.json", True),
            ("documentation.yaml", "documentation-config.schema.json", False),
            ("request-profiles.yaml", "request-profiles.schema.json", False),
        ]:
            errors.extend(self._validate_yaml_file(file, schema, required=required))

        profile_pack_dir = self.config_dir / "profile-packs"
        if profile_pack_dir.exists():
            schema = "profile-pack.schema.json"
            for path in sorted(profile_pack_dir.glob("*.yaml")):
                sch = json.loads((self.schemas / schema).read_text(encoding="utf-8"))
                inst = yaml.safe_load(path.read_text(encoding="utf-8"))
                v = Draft202012Validator(sch)
                for e in v.iter_errors(inst):
                    errors.append(f"config profile-packs/{path.name}: {e.message}")
        return errors

    def workflow_for(self, kind: str, name: str | None = None) -> dict:
        group = self.workflows["planning"]["workflows"][kind]
        wf_name = name or group["default"]
        return group["named"][wf_name]

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
        profiles = self.profiles.get("planning", {}).get("profiles", {})
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
        defaults = self.profiles.get("planning", {}).get("standard_defaults", {})
        return defaults.get(kind, [])

    def guidance_levels(self) -> dict:
        """Get all guidance levels.

        Returns:
            Dict of guidance levels (light, standard, deep)
        """
        return self.profiles.get("planning", {}).get("guidance_levels", {})

    def guidance_for(self, name: str) -> dict:
        """Get a specific guidance level by name.

        Args:
            name: Guidance level name (light, standard, deep)

        Returns:
            Guidance level config dict

        Raises:
            ValueError: If guidance level not found
        """
        levels = self.guidance_levels()
        if name not in levels:
            raise ValueError(f"guidance level '{name}' not found")
        return levels[name]

    def default_guidance(self) -> str:
        """Get the default guidance level from planning.yaml.

        Returns:
            Default guidance level (light, standard, or deep)
        """
        return self.planning.get("planning", {}).get("default_guidance", "standard")

    def default_profile(self) -> str:
        """Get the default profile from planning.yaml.

        Returns:
            Default profile name (feature, issue, fix, enhancement)
        """
        return self.planning.get("planning", {}).get("default_profile", "feature")

    def document_template(self, kind: str, guidance: str | None = None) -> str:
        """Get document body template for a planning kind.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')
            guidance: Optional guidance level ('light', 'standard', 'deep'). If not provided,
                     uses the default template or falls back to current default guidance.

        Returns:
            Template string with section headers
        """
        templates = self.profiles.get("planning", {}).get("document_templates", {})
        kind_config = templates.get(kind, {})

        if guidance and "by_guidance" in kind_config:
            guidance_templates = kind_config.get("by_guidance", {})
            if guidance in guidance_templates:
                return guidance_templates[guidance]

        return kind_config.get("default", "")

    def relationship_rules(self, kind: str) -> dict:
        """Get relationship rules for a planning kind.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')

        Returns:
            Dict with can_reference, required_for_children, referenced_by
        """
        rel_config = self.profiles.get("planning", {}).get("relationship_config", {})
        return rel_config.get(
            kind, {"can_reference": [], "required_for_children": [], "referenced_by": {}}
        )

    def can_reference(self, from_kind: str, to_kind: str) -> bool:
        """Check if a kind can reference another kind.

        Args:
            from_kind: Source planning kind
            to_kind: Target planning kind being referenced

        Returns:
            True if the reference is allowed
        """
        rules = self.relationship_rules(from_kind)
        return to_kind in rules.get("can_reference", [])

    def required_refs(self, kind: str) -> list[str]:
        """Get required reference fields for a planning kind.

        Args:
            kind: Planning kind

        Returns:
            List of required reference field names (e.g. ['spec_ref', 'request_refs'])
        """
        rules = self.relationship_rules(kind)
        return rules.get("required_for_children", [])

    def required_sections(self, kind: str) -> list[str] | None:
        """Get required sections for a planning kind.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')

        Returns:
            List of required section names, or None if not configured
        """
        req_sections = self.profiles.get("planning", {}).get("required_sections", {})
        return req_sections.get(kind)

    def kind_config(self, kind: str) -> dict:
        """Get configuration for a planning kind from planning.yaml.

        Args:
            kind: Planning kind name

        Returns:
            Kind config dict with dir, id_prefix, counter_file, has_domain, required_refs

        Raises:
            ValueError: If kind not found in config
        """
        kinds = self.planning.get("planning", {}).get("kinds", {})
        if kind not in kinds:
            raise ValueError(
                f"Kind '{kind}' not found in config. Available kinds: {list(kinds.keys())}"
            )
        return kinds[kind]

    def all_kinds(self) -> list[str]:
        """Get all defined kind names from config.

        Returns:
            List of kind names
        """
        return list(self.planning.get("planning", {}).get("kinds", {}).keys())

    def kind_counter_file(self, kind: str) -> str:
        """Get counter file name for a kind.

        Args:
            kind: Planning kind name

        Returns:
            Counter file name (e.g., 'requests.json', 'tasks.json')
        """
        kind_cfg = self.kind_config(kind)
        return kind_cfg.get("counter_file", f"{kind}s.json")

    def kind_id_prefix(self, kind: str) -> str:
        """Get ID prefix for a kind.

        Args:
            kind: Planning kind name

        Returns:
            ID prefix (e.g., 'req', 'spec', 'task')
        """
        kind_cfg = self.kind_config(kind)
        return kind_cfg.get("id_prefix", kind)

    def kind_has_domain(self, kind: str) -> bool:
        """Check if a kind supports domains.

        Args:
            kind: Planning kind name

        Returns:
            True if kind has domain support (e.g., task, wp)
        """
        kind_cfg = self.kind_config(kind)
        return kind_cfg.get("has_domain", False)

    def kind_required_refs(self, kind: str) -> list[str]:
        """Get required reference fields for a kind.

        Args:
            kind: Planning kind name

        Returns:
            List of required reference field names
        """
        kind_cfg = self.kind_config(kind)
        return kind_cfg.get("required_refs", [])

    def standard_refs_inheritance(self, kind: str) -> list[dict]:
        """Get standard_refs inheritance rules for a kind.

        Args:
            kind: Planning kind name

        Returns:
            List of inheritance rules, each with:
            - field: The reference field to follow (e.g., 'spec_ref', 'task_refs')
            - type: 'direct' (follow field once) or 'recursive' (follow with sub_inheritance)
            - sub_inheritance: (for recursive) list of fields to inherit from the referenced item
        """
        kind_cfg = self.kind_config(kind)
        return kind_cfg.get("standard_refs_inheritance", [])
