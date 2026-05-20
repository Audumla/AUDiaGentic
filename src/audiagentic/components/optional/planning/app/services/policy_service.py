from __future__ import annotations


class PolicyService:
    def __init__(self, api):
        self.api = api

    def assert_not_terminal(self, item, action: str) -> None:
        if self.api.config.state_in_set(
            item.kind,
            item.data.get("state"),
            "terminal",
            item.data.get("workflow"),
        ):
            state = item.data.get("state")
            raise ValueError(f"cannot {action} terminal item {item.data['id']} in state {state}")

    def validate_ref_fields(self, refs: dict[str, object], fields: list[str]) -> None:
        """Validate that provided ref values point to configured target kinds.

        Args:
            refs: Dict of reference field name -> value(s)
            fields: List of field names to validate

        Raises:
            ValueError if any configured field has no target config, or if any
            ref value does not match one of the configured target kinds.
        """
        for field in fields:
            target_kinds = self.api.config.reference_field_targets(field)
            if not target_kinds:
                raise ValueError(
                    f"validation field '{field}' has no reference_field_targets config"
                )

            values = refs.get(field)
            if values in (None, "", []):
                continue

            if not isinstance(values, list):
                values = [values]

            for ref_id in values:
                item = self.api._find(ref_id)
                if item.kind not in target_kinds:
                    expected = ", ".join(target_kinds)
                    raise ValueError(f"'{ref_id}' must reference one of: {expected}")

    def check_duplicate(self, kind: str, label: str, summary: str) -> None:
        label_key = label.strip().lower()
        for item in self.api._scan():
            if item.kind != kind or self.api.config.is_soft_deleted(item.data):
                continue
            existing_label = str(item.data.get("label", "")).strip().lower()
            if existing_label == label_key:
                raise ValueError(
                    f"{kind} already exists: {item.data['id']} ({item.data.get('label', '')})"
                )
