from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Schemas are bundled with the audiagentic package, not in the project root.
# From app/config.py: parents[2] = src/audiagentic/
_PLANNING_SCHEMA_DIR = (
    Path(__file__).resolve().parents[2] / "foundation" / "contracts" / "schemas" / "planning"
)
_REPO_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[4] / ".audiagentic" / "planning" / "config" / "templates"
)
_SECTION_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


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
        self.propagation = self._read_optional_yaml("state_propagation.yaml")
        self.profile_packs = self._read_profile_packs()

    def kind_aliases(self) -> dict[str, str]:
        """Get configured kind aliases."""
        return self.planning.get("planning", {}).get("kind_aliases", {})

    def normalize_kind(self, kind: str) -> str:
        """Normalize alias or long-form kind name to canonical config kind."""
        return self.kind_aliases().get(kind, kind)

    def _template_dir(self) -> Path:
        return self.config_dir / "templates"

    def _template_path(self, kind: str, guidance: str | None = None) -> Path:
        normalized_kind = self.normalize_kind(kind)
        template_name = f"{guidance}.md" if guidance else "default.md"
        return self._template_dir() / normalized_kind / template_name

    def _template_candidates(self, kind: str, guidance: str | None = None) -> list[Path]:
        normalized_kind = self.normalize_kind(kind)
        template_name = f"{guidance}.md" if guidance else "default.md"
        return [
            self._template_dir() / normalized_kind / template_name,
            _REPO_TEMPLATE_DIR / normalized_kind / template_name,
        ]

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
            ("state_propagation.yaml", "state-propagation.schema.json", False),
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

    def initial_state(self, kind: str, workflow: str | None = None) -> str:
        """Get configured initial state for a kind/workflow."""
        wf = self.workflow_for(kind, workflow)
        return wf["initial"]

    def standard_ref_field(self) -> str:
        """Get configured standard-reference field name."""
        return self.planning["planning"]["standard_ref_field"]

    def standard_kind(self) -> str:
        """Get kind targeted by the configured standard-reference field."""
        targets = self.reference_field_targets(self.standard_ref_field())
        if not targets:
            raise ValueError("planning.standard_ref_field must target a configured kind")
        return targets[0]

    def kind_for_id(self, id_: str) -> str | None:
        """Infer configured kind from an item id prefix."""
        for kind in self.all_kinds():
            prefix = self.kind_id_prefix(kind)
            if id_ == prefix or id_.startswith(f"{prefix}-"):
                return kind
        return None

    def default_workflow_name(self, kind: str) -> str:
        """Get the default workflow name for a kind."""
        return self.workflows["planning"]["workflows"][kind]["default"]

    def resolved_workflow_name(self, kind: str, workflow: str | None = None) -> str:
        """Resolve explicit workflow or return the configured default."""
        return workflow or self.default_workflow_name(kind)

    def workflow_states(self, kind: str, workflow: str | None = None) -> list[str]:
        """Get all valid states for a kind from its workflow config."""
        wf = self.workflow_for(kind, workflow)
        return list(wf.get("values", []))

    def state_sets(self, kind: str, workflow: str | None = None) -> dict[str, list[str]]:
        """Get configured semantic state sets for a kind/workflow."""
        lifecycle = self.planning.get("planning", {}).get("lifecycle", {})
        all_sets = lifecycle.get("state_sets", {})
        workflow_sets = all_sets.get(kind, {}).get(self.resolved_workflow_name(kind, workflow), {})
        return workflow_sets if isinstance(workflow_sets, dict) else {}

    def states_in_set(self, kind: str, set_name: str, workflow: str | None = None) -> list[str]:
        """Get states in a configured semantic set for a kind/workflow."""
        sets = self.state_sets(kind, workflow)
        if set_name in sets:
            return list(sets.get(set_name, []) or [])
        return []

    def state_in_set(
        self, kind: str, state: str | None, set_name: str, workflow: str | None = None
    ) -> bool:
        """Return True when a state belongs to a configured semantic set."""
        if not state:
            return False
        return state in self.states_in_set(kind, set_name, workflow)

    def state_set_priority(self, set_name: str) -> int:
        """Get configured semantic priority for a state set."""
        lifecycle = self.planning.get("planning", {}).get("lifecycle", {})
        priorities = lifecycle.get("state_set_priority", {})
        return int(priorities.get(set_name, 0))

    def state_priority(self, kind: str, state: str | None, workflow: str | None = None) -> int:
        """Derive state priority from configured semantic state sets."""
        if not state:
            return 0

        priorities = [
            self.state_set_priority(set_name)
            for set_name in self.state_sets(kind, workflow).keys()
            if self.state_in_set(kind, state, set_name, workflow)
        ]
        return max(priorities, default=0)

    def lifecycle_actions(self) -> dict[str, dict]:
        """Get configured lifecycle actions."""
        lifecycle = self.planning.get("planning", {}).get("lifecycle", {})
        actions = lifecycle.get("actions", {})
        return actions if isinstance(actions, dict) else {}

    def lifecycle_action(self, name: str) -> dict:
        """Get one lifecycle action."""
        actions = self.lifecycle_actions()
        if name not in actions:
            raise ValueError(f"lifecycle action '{name}' is not configured")
        return dict(actions[name])

    def lifecycle_action_state(self, name: str) -> str:
        """Get transition target state for a lifecycle action."""
        action = self.lifecycle_action(name)
        state = action.get("transition_to")
        if not isinstance(state, str) or not state:
            raise ValueError(f"lifecycle action '{name}' has no transition_to state")
        return state

    def lifecycle_metadata_fields(self) -> list[str]:
        """Get all metadata fields managed by lifecycle actions."""
        fields: set[str] = set()
        for action in self.lifecycle_actions().values():
            metadata = action.get("metadata", {})
            if isinstance(metadata, dict):
                fields.update(metadata.keys())
        return sorted(fields)

    def lifecycle_action_for_transition(
        self,
        kind: str,
        old_state: str,
        new_state: str,
        workflow: str | None = None,
    ) -> tuple[str, dict] | tuple[None, None]:
        """Find lifecycle action matching state transition."""
        for name, action in self.lifecycle_actions().items():
            if action.get("transition_to") == new_state:
                return name, dict(action)
            if action.get("from_state") == old_state:
                return name, dict(action)
            from_set = action.get("from_state_set")
            if from_set and self.state_in_set(kind, old_state, from_set, workflow):
                return name, dict(action)
        return None, None

    def creation_profiles(self) -> dict[str, dict]:
        """Get all configured creation profiles."""
        return self.profiles.get("planning", {}).get("profiles", {})

    def creation_profile_for(self, name: str) -> dict:
        """Load a generic creation profile by name."""
        profiles = self.creation_profiles()
        if name not in profiles:
            raise ValueError(f"profile '{name}' not found")
        return profiles[name]

    def default_reference_values(self, kind: str, field: str) -> list[str]:
        """Get default reference values for a kind/field pair."""
        defaults = self.profiles.get("planning", {}).get("default_references", {})
        kind_defaults = defaults.get(kind, {})
        return list(kind_defaults.get(field, []) or [])

    def guidance_levels(self) -> dict:
        """Get all guidance levels.

        Returns:
            Dict of configured guidance levels
        """
        return self.profiles.get("planning", {}).get("guidance_levels", {})

    def guidance_for(self, name: str) -> dict:
        """Get a specific guidance level by name.

        Args:
            name: Guidance level name

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
            Default guidance level name
        """
        planning = self.planning.get("planning", {})
        if "default_guidance" not in planning:
            raise ValueError("planning.default_guidance is required")
        return planning["default_guidance"]

    def default_profile(self) -> str:
        """Get the default profile from planning.yaml.

        Returns:
            Default profile name
        """
        planning = self.planning.get("planning", {})
        if "default_profile" not in planning:
            raise ValueError("planning.default_profile is required")
        return planning["default_profile"]

    def guidance_sections_for(self, guidance: str, kind: str) -> dict:
        """Get guidance-driven section config for a kind.

        Uses generic `sections_by_kind.<kind>` configuration.
        """
        guidance_cfg = self.guidance_for(guidance)
        by_kind = guidance_cfg.get("sections_by_kind", {})
        if kind in by_kind:
            return by_kind.get(kind, {}) or {}
        return {}

    def guidance_required_sections(self, guidance: str, kind: str) -> list[str]:
        """Get guidance-required sections for a kind."""
        return list(self.guidance_sections_for(guidance, kind).get("required", []) or [])

    def guidance_suggested_sections(self, guidance: str, kind: str) -> list[str]:
        """Get guidance-suggested sections for a kind."""
        return list(self.guidance_sections_for(guidance, kind).get("suggested", []) or [])

    def document_template(self, kind: str, guidance: str | None = None) -> str:
        """Get document body template for a planning kind.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')
            guidance: Optional guidance level ('light', 'standard', 'deep'). If not provided,
                     uses the default template or falls back to current default guidance.

        Returns:
            Template string with section headers
        """
        for template_path in self._template_candidates(kind, guidance):
            if template_path.exists():
                return template_path.read_text(encoding="utf-8")

        if guidance:
            for default_template_path in self._template_candidates(kind):
                if default_template_path.exists():
                    return default_template_path.read_text(encoding="utf-8")

        # Inline templates are allowed for compact greenfield configs.
        templates = self.profiles.get("planning", {}).get("document_templates", {})
        kind_config = templates.get(kind, {})

        if guidance and "by_guidance" in kind_config:
            guidance_templates = kind_config.get("by_guidance", {})
            if guidance in guidance_templates:
                return guidance_templates[guidance]

        return kind_config.get("default", "")

    def creation_sections(
        self,
        kind: str,
        guidance: str | None = None,
        profile: str | None = None,
    ) -> list[str]:
        """Get ordered document sections for newly created items.

        Uses existing template headings as base source of truth, then layers on
        minimal profile- and validator-driven additions where creation should
        include extra sections by default.
        """
        sections = _SECTION_HEADING_RE.findall(self.document_template(kind, guidance))
        extra = self.creation_rules(kind).get("extra_fields", {})
        if not extra:
            return sections

        profile_cfg = self.creation_profile_for(profile) if profile else {}
        profile_sections = profile_cfg.get("suggested_sections", []) if extra.get("use_profile_sections") else []
        required_sections = self.required_sections(kind) if extra.get("use_required_sections") else []
        ordered: list[str] = []
        for section in [*sections, *required_sections, *profile_sections]:
            if section and section not in ordered:
                ordered.append(section)
        return ordered

    def creation_template(
        self,
        kind: str,
        guidance: str | None = None,
        profile: str | None = None,
    ) -> str:
        """Render default creation body from configured sections."""
        sections = self.creation_sections(kind, guidance=guidance, profile=profile)
        if not sections:
            return ""
        return "".join(f"# {section}\n\n\n" for section in sections)

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

    def referenced_by(self, kind: str) -> dict[str, str]:
        """Get child-kind -> field mapping for items that reference this kind."""
        return self.relationship_rules(kind).get("referenced_by", {})

    def back_ref_rule(self, parent_kind: str, child_kind: str) -> str | None:
        """Get the back-reference field name on the parent for tracking child items.

        Looks up relationship_config to find the field on `parent_kind` that stores
        references to `child_kind` items. Uses the child kind's configured forward
        reference field to derive the parent's tracking field.

        Args:
            parent_kind: Kind being referenced (e.g., 'request')
            child_kind: Kind doing the referencing (e.g., 'spec')

        Returns:
            Field name on parent (e.g., 'spec_refs'), or None if no back-ref configured.
        """
        child_rules = self.relationship_rules(child_kind)
        forward_field = child_rules.get("required_for_children", [])
        if not forward_field:
            return None

        parent_refs = self.referenced_by(parent_kind)
        if child_kind not in parent_refs:
            return None

        forward_ref_field = parent_refs[child_kind]
        target_name = forward_ref_field
        if target_name.endswith("_refs"):
            target_name = target_name[: -len("_refs")]
        elif target_name.endswith("_ref"):
            target_name = target_name[: -len("_ref")]
        else:
            return None

        return f"{child_kind}_refs"

    def requires_children(self, kind: str) -> dict[str, list[str]]:
        """Get configured downstream-child requirements for a kind.

        Returns:
            Mapping of child kind -> workflow states where at least one such child must exist.
        """
        rules = self.relationship_rules(kind).get("requires_children", {})
        out: dict[str, list[str]] = {}
        for child_kind, child_rules in rules.items():
            if isinstance(child_rules, dict):
                out[child_kind] = child_rules.get("states", [])
        return out

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
        if kind in req_sections:
            return req_sections.get(kind)
        template = self.document_template(kind)
        if not template:
            return None
        return _SECTION_HEADING_RE.findall(template)

    def state_required_sections(self, kind: str, state: str | None) -> list[str]:
        """Get extra required sections for a kind when in a specific workflow state.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')
            state: Workflow state name

        Returns:
            List of section names required for this kind/state combination.
        """
        if not state:
            return []
        requirements = self.profiles.get("planning", {}).get("state_section_requirements", {})
        kind_rules = requirements.get(kind, {})
        return kind_rules.get(state, [])

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

    def creation_rules(self, kind: str) -> dict:
        """Get create-time behavior rules for a kind."""
        return self.kind_config(kind).get("creation", {})

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

    def kind_dir_name(self, kind: str) -> str:
        """Get configured directory name for a kind."""
        kind_cfg = self.kind_config(kind)
        return kind_cfg["dir"]

    def reference_fields(self, kind: str) -> list[str]:
        """Get configured reference-like frontmatter fields for a kind."""
        fields = set(self.required_fields(kind) + self.optional_fields(kind))
        fields.update(self.kind_required_refs(kind))
        return sorted(
            field for field in fields if field.endswith("_ref") or field.endswith("_refs")
        )

    def seeded_reference_fields(self, kind: str) -> dict[str, str]:
        """Get target ref field -> source input field seed mapping for creation."""
        return self.creation_rules(kind).get("seed_reference_fields", {})

    def all_reference_fields(self) -> list[str]:
        """Get all configured reference-like fields across kinds."""
        fields: set[str] = set()
        for kind in self.all_kinds():
            fields.update(self.reference_fields(kind))
        return sorted(fields)

    def reference_field_shape(self, field: str) -> str:
        """Classify reference field storage shape.

        Returns one of:
        - scalar_ref: single string id
        - scalar_ref_list: list of string ids
        - rel_list: list of {'ref', ...} objects
        """
        configured = self.planning.get("planning", {}).get("reference_field_shapes", {})
        if field in configured:
            return configured[field]
        if field.endswith("_ref"):
            return "scalar_ref"
        if field.endswith("_refs"):
            return "scalar_ref_list"
        raise ValueError(f"field '{field}' is not a reference field")

    def reference_field_targets(self, field: str) -> list[str]:
        """Infer target planning kinds for a reference field."""
        configured = self.planning.get("planning", {}).get("reference_field_targets", {})
        if field in configured:
            target = configured[field]
            if isinstance(target, str) and target in self.all_kinds():
                return [target]
            if isinstance(target, list):
                return [entry for entry in target if entry in self.all_kinds()]
            return []

        target_name = field
        if target_name.endswith("_refs"):
            target_name = target_name[: -len("_refs")]
        elif target_name.endswith("_ref"):
            target_name = target_name[: -len("_ref")]
        else:
            return []

        normalized = self.normalize_kind(target_name)
        return [normalized] if normalized in self.all_kinds() else []

    def workflow_action(self, name: str) -> dict:
        """Get config for a named workflow action."""
        actions = self.planning.get("planning", {}).get("workflow_actions", {})
        if name not in actions:
            raise ValueError(f"workflow action '{name}' is not configured")
        return dict(actions[name])

    def queue_defaults(self) -> dict:
        """Get default kind/state for queue listing."""
        defaults = self.planning.get("planning", {}).get("queue_defaults", {})
        if "kind" not in defaults or "state" not in defaults:
            raise ValueError("planning.queue_defaults.kind/state must be configured")
        return dict(defaults)

    def should_duplicate_check(self, kind: str) -> bool:
        return bool(self.creation_rules(kind).get("duplicate_check"))

    def requires_source_on_create(self, kind: str) -> bool:
        return bool(self.creation_rules(kind).get("require_source"))

    def validate_ref_fields_on_create(self, kind: str) -> list[str]:
        """Get list of ref fields to validate on create for a kind."""
        fields = self.creation_rules(kind).get("validate_ref_fields", [])
        return fields if isinstance(fields, list) else []

    def refinement_source_prefix(self, kind: str) -> str | None:
        value = self.creation_rules(kind).get("refinement_source_prefix")
        return value if isinstance(value, str) and value else None

    def refinement_action(self, kind: str) -> str | None:
        """Get the lifecycle action name to apply when refinement is detected."""
        value = self.creation_rules(kind).get("refinement_action")
        return value if isinstance(value, str) and value else None

    def profile_cascade_targets(self, profile: str | None) -> list[dict]:
        """Get cascade targets for a creation profile.

        Returns a list of dicts with keys: kind, label_suffix (optional), domain (optional).
        """
        if not profile:
            return []
        profile_cfg = self.creation_profile_for(profile)
        return profile_cfg.get("on_create", [])

    def build_creation_extra_fields(
        self,
        kind: str,
        *,
        summary: str,
        guidance: str | None,
        profile: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
    ) -> dict:
        """Build config-driven create-time frontmatter extras for a kind."""
        rules = self.creation_rules(kind)
        extra = rules.get("extra_fields", {})
        if not extra:
            return {}

        if guidance is None:
            guidance = self.default_guidance()

        fields: dict[str, object] = {}
        if source_field := extra.get("source_field"):
            fields[source_field] = source or ""
        if guidance_field := extra.get("guidance_field"):
            fields[guidance_field] = guidance
        if context and (context_field := extra.get("context_field")):
            fields[context_field] = context

        defaults = {}
        if extra.get("use_profile_defaults") and profile:
            defaults = self.creation_profile_for(profile).get("defaults", {})

        guidance_defaults = {}
        if extra.get("use_guidance_defaults"):
            guidance_defaults = self.guidance_for(guidance).get("defaults", {})

        understanding_field = extra.get("understanding_field")
        if understanding_field:
            understanding = (
                current_understanding
                or defaults.get("current_understanding")
                or guidance_defaults.get("current_understanding")
            )
            if understanding is None:
                raise ValueError(
                    f"creation.extra_fields.{understanding_field} requires configured default"
                )
            fields[understanding_field] = understanding

        open_questions_field = extra.get("open_questions_field")
        if open_questions_field:
            fields[open_questions_field] = (
                open_questions
                if open_questions is not None
                else (
                    defaults.get("open_questions") or guidance_defaults.get("open_questions") or []
                )
            )

        meta_field = extra.get("meta_field")
        if meta_field and defaults.get("meta"):
            fields[meta_field] = defaults["meta"]

        return fields

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

    def reference_inheritance(self, kind: str, target_field: str) -> list[dict]:
        """Get generic inheritance rules for a reference field on a kind."""
        kind_cfg = self.kind_config(kind)
        generic = kind_cfg.get("reference_inheritance", {}) or {}
        return generic.get(target_field, []) or []

    def required_fields(self, kind: str) -> list[str]:
        """Get required fields for a kind.

        Args:
            kind: Planning kind name

        Returns:
            List of required field names
        """
        kind_cfg = self.kind_config(kind)
        base = self.planning["planning"].get("base_required_fields", [])
        fields = list(base)
        fields.extend(field for field in kind_cfg.get("required_fields", []) if field not in fields)
        return fields

    def optional_fields(self, kind: str) -> list[str]:
        """Get optional fields for a kind.

        Args:
            kind: Planning kind name

        Returns:
            List of optional field names
        """
        kind_cfg = self.kind_config(kind)
        base = self.planning["planning"].get("base_optional_fields", [])
        fields = list(base)
        fields.extend(field for field in kind_cfg.get("optional_fields", []) if field not in fields)
        fields.extend(field for field in self.lifecycle_metadata_fields() if field not in fields)
        return fields
