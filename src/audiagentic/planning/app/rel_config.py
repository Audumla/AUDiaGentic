from __future__ import annotations

from typing import Any


class RelationshipConfig:
    """Validate and manage document relationships from config.

    This class provides validation for references between planning documents
    based on configurable relationship rules, eliminating hardcoded validation
    logic in individual managers.
    """

    def __init__(self, config: Any):
        """Initialize with config instance.

        Args:
            config: Config instance with relationship_config
        """
        self.config = config

    def can_reference(self, from_kind: str, to_kind: str) -> bool:
        """Check if a kind can reference another kind.

        Args:
            from_kind: Source planning kind
            to_kind: Target planning kind being referenced

        Returns:
            True if the reference is allowed
        """
        return self.config.can_reference(from_kind, to_kind)

    def required_refs(self, kind: str) -> list[str]:
        """Get required reference fields for a planning kind.

        Args:
            kind: Planning kind

        Returns:
            List of required reference field names
        """
        return self.config.required_refs(kind)

    def get_rules(self, kind: str) -> dict:
        """Get all relationship rules for a kind.

        Args:
            kind: Planning kind

        Returns:
            Dict with can_reference, required_for_children, referenced_by
        """
        return self.config.relationship_rules(kind)

    def validate_refs(self, kind: str, data: dict, *, validate_required: bool = True) -> list[str]:
        """Validate references in document data.

        Args:
            kind: Planning kind
            data: Document metadata dict
            validate_required: Whether to enforce required relationship fields

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        rules = self.get_rules(kind)

        if validate_required:
            for field in rules.get("required_for_children", []):
                if field not in data or not data[field]:
                    errors.append(f"Missing required reference: {field}")

        can_ref = set(rules.get("can_reference", []))
        allowed_by_field = {
            "request_refs": {"request"},
            "spec_ref": {"spec"},
            "spec_refs": {"spec"},
            "standard_refs": {"standard"},
            "task_refs": {"task"},
            "plan_ref": {"plan"},
            "parent_task_ref": {"task"},
        }
        ref_fields = {
            "request_refs",
            "spec_ref",
            "spec_refs",
            "task_refs",
            "plan_ref",
            "parent_task_ref",
        }
        if kind in {"spec", "task", "plan", "wp"}:
            ref_fields.add("standard_refs")

        for field in ref_fields:
            if field not in data:
                continue

            refs = data[field]
            if isinstance(refs, str):
                refs = [refs]
            elif not isinstance(refs, list):
                continue

            for ref in refs:
                if isinstance(ref, dict):
                    ref = ref.get("ref")
                allowed_kinds = allowed_by_field.get(field, can_ref | {kind})
                if ref and not ref.startswith(tuple(allowed_kinds)):
                    errors.append(
                        f"Invalid reference '{ref}' for field '{field}' on {kind} - "
                        f"expected {sorted(allowed_kinds)}"
                    )

        return errors
