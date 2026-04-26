from __future__ import annotations

import re
from pathlib import Path

from ..fs.scan import scan_items
from .config import Config
from .paths import Paths
from .util import body_has_section

_ID_PATTERN = re.compile(r'^[a-z]+-([1-9]\d*|0)$')


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.config = Config(root)
        self.paths = Paths(root)

    def _get_required_sections(self, kind: str) -> list[str]:
        """Get required sections for a kind from config."""
        return self.config.required_sections(kind) or []

    def _get_state_required_sections(self, kind: str, state: str | None) -> list[str]:
        """Get extra required sections for a kind/state pair from config."""
        return self.config.state_required_sections(kind, state)

    @staticmethod
    def _iter_ref_ids(value) -> list[str]:
        """Normalize reference values to bare ID strings."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            refs: list[str] = []
            for entry in value:
                if isinstance(entry, str):
                    refs.append(entry)
                elif isinstance(entry, dict):
                    ref = entry.get("ref")
                    if isinstance(ref, str):
                        refs.append(ref)
            return refs
        if isinstance(value, dict):
            ref = value.get("ref")
            return [ref] if isinstance(ref, str) else []
        return []

    def _child_refs_parent(self, child_item, parent_kind: str, parent_id: str) -> bool:
        """Return True if child item references the given parent via configured field."""
        field = self.config.referenced_by(parent_kind).get(child_item.kind)
        if not field:
            return False
        return parent_id in self._iter_ref_ids(child_item.data.get(field))

    def _validate_reference_targets(self, item, items) -> list[str]:
        """Validate configured references resolve to existing items of allowed target kind."""
        errors: list[str] = []
        for field in self.config.reference_fields(item.kind):
            targets = set(self.config.reference_field_targets(field))
            if not targets:
                continue
            for ref_id in self._iter_ref_ids(item.data.get(field)):
                found = any(i.data["id"] == ref_id and i.kind in targets for i in items)
                if not found:
                    target_desc = "/".join(sorted(targets))
                    errors.append(
                        f"{item.path}: {field} references non-existent {target_desc} '{ref_id}'"
                    )
        return errors

    def _validate_item_against_config(self, item) -> list[str]:
        """Validate an item against config-driven field rules.

        Args:
            item: Item to validate

        Returns:
            List of validation errors
        """
        errors = []
        kind = item.kind

        # Get config-driven field definitions
        required_fields = self.config.required_fields(kind) or []
        optional_fields = self.config.optional_fields(kind) or []
        allowed_fields = set(required_fields + optional_fields)
        allowed_fields.update(self.config.reference_fields(kind))
        kind_cfg = self.config.kind_config(kind)
        if kind_cfg.get("has_domain"):
            allowed_fields.add("domain")

        # Check required fields
        for field in required_fields:
            if field not in item.data:
                errors.append(f"{item.path}: missing required field '{field}'")

        # Check for unknown fields
        for field in item.data.keys():
            if field not in allowed_fields:
                errors.append(
                    f"{item.path}: unknown field '{field}', move to meta or add to config"
                )

        # Validate relationship field formats. Legacy string lists are still accepted.
        for field in self.config.reference_fields(kind):
            shape = self.config.reference_field_shape(field)
            if shape == "scalar_ref":
                continue
            if field in item.data:
                value = item.data[field]
                if isinstance(value, list):
                    for i, entry in enumerate(value):
                        if shape == "rel_list":
                            if isinstance(entry, dict):
                                if "ref" not in entry:
                                    errors.append(
                                        f"{item.path}: {field}[{i}] missing required 'ref' field"
                                    )
                            else:
                                errors.append(
                                    f"{item.path}: {field} must be a list of objects with 'ref'"
                                )
                        elif isinstance(entry, dict) and "ref" not in entry:
                            errors.append(f"{item.path}: {field}[{i}] missing required 'ref' field")
                elif not isinstance(value, str):
                    if shape == "rel_list":
                        errors.append(
                            f"{item.path}: {field} must be a list of objects with 'ref'"
                        )
                    else:
                        errors.append(
                            f"{item.path}: {field} must be a string, list of strings, or list of ref objects"
                        )

        return errors

    def validate_all(self) -> list[str]:
        errors = []
        errors.extend(self.config.validate())
        items = list(scan_items(self.root))
        ids = set()

        for item in items:
            if item.data["id"] in ids:
                errors.append(f"duplicate id: {item.data['id']}")
            ids.add(item.data["id"])

            # Validate ID format: kind-integer with no padding
            item_id = item.data["id"]
            if not _ID_PATTERN.match(item_id):
                errors.append(f"{item.path}: id '{item_id}' does not match format '<kind>-<integer>'")

            # Validate against config-driven field rules
            errors.extend(self._validate_item_against_config(item))

            # Validate filename conventions
            expected_name = self.paths.filename_for(item.kind, item.data["id"], item.data["label"])
            if item.path.name != expected_name:
                errors.append(f"{item.path}: filename must be {expected_name}")
        # Check sections and path structure (single pass)
        for item in items:
            # Check guidance-appropriate sections
            if item.data.get("guidance"):
                guidance = item.data["guidance"]
                for sec in self.config.guidance_required_sections(guidance, item.kind):
                    if not body_has_section(item.body, sec):
                        errors.append(
                            f"{item.path}: missing required section '{sec}' for {guidance} guidance"
                        )

            # Check required sections for kind
            for sec in self._get_required_sections(item.kind):
                if not body_has_section(item.body, sec):
                    errors.append(f"{item.path}: missing section '{sec}'")

            # Check extra required sections for current workflow state
            for sec in self._get_state_required_sections(item.kind, item.data.get("state")):
                if not body_has_section(item.body, sec):
                    state = item.data.get("state")
                    errors.append(f"{item.path}: missing section '{sec}' for state '{state}'")

            # Check path structure
            if self.config.kind_has_domain(item.kind):
                if item.path.parent.parent.name != self.config.kind_dir_name(item.kind):
                    errors.append(
                        f"{item.path}: {item.kind} must be under "
                        f"{self.config.kind_dir_name(item.kind)}/<domain>/"
                    )

        # Referential integrity checks
        for item in items:
            if item.data.get("deleted"):
                continue
            if self.config.state_in_set(
                item.kind, item.data.get("state"), "terminal", item.data.get("workflow")
            ):
                continue

            errors.extend(self._validate_reference_targets(item, items))

            for child_kind, states in self.config.requires_children(item.kind).items():
                if item.data.get("state") not in states:
                    continue
                has_child = any(
                    child.kind == child_kind
                    and not child.data.get("deleted")
                    and not self.config.state_in_set(
                        child.kind,
                        child.data.get("state"),
                        "terminal",
                        child.data.get("workflow"),
                    )
                    and self._child_refs_parent(child, item.kind, item.data["id"])
                    for child in items
                )
                if not has_child:
                    errors.append(
                        f"{item.path}: {item.kind} in '{item.data['state']}' state has no {child_kind} references"
                    )

        return errors
