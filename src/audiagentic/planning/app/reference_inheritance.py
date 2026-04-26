from __future__ import annotations

from .api_types import ItemView
from .config import Config


def _extend_unique(refs: list[str], values: list[str]) -> None:
    for value in values:
        if value not in refs:
            refs.append(value)


def _collect_inherited_reference_values(
    item: ItemView,
    target_field: str,
    items_by_id: dict[str, ItemView],
    config: Config,
    visited: set[str] | None = None,
) -> list[str]:
    """Recursively collect effective values for a reference field from config."""
    if visited is None:
        visited = set()

    item_id = item.data.get("id")
    if item_id in visited:
        return []
    visited.add(item_id)

    refs = list(item.data.get(target_field, []) or [])
    inheritance_rules = config.reference_inheritance(item.kind, target_field)

    for rule in inheritance_rules:
        field = rule.get("field")
        rule_type = rule.get("type", "direct")

        if rule_type == "direct":
            ref_id = item.data.get(field)
            if ref_id and ref_id in items_by_id:
                ref_item = items_by_id[ref_id]
                _extend_unique(refs, list(ref_item.data.get(target_field, []) or []))

        elif rule_type == "recursive":
            ref_list = item.data.get(field, []) or []
            sub_inheritance = rule.get("sub_inheritance", [])

            for ref_entry in ref_list:
                ref_id = ref_entry.get("ref") if isinstance(ref_entry, dict) else ref_entry
                if not ref_id or ref_id not in items_by_id:
                    continue
                ref_item = items_by_id[ref_id]

                for sub_rule in sub_inheritance:
                    sub_field = sub_rule.get("field")
                    sub_type = sub_rule.get("type", "direct")

                    if sub_type == "direct":
                        sub_ref_id = ref_item.data.get(sub_field)
                        if sub_ref_id and sub_ref_id in items_by_id:
                            sub_ref_item = items_by_id[sub_ref_id]
                            _extend_unique(
                                refs, list(sub_ref_item.data.get(target_field, []) or [])
                            )
                    elif sub_type == "recursive":
                        sub_refs = ref_item.data.get(sub_field, []) or []
                        for sub_ref_entry in sub_refs:
                            sub_ref_id = (
                                sub_ref_entry.get("ref")
                                if isinstance(sub_ref_entry, dict)
                                else sub_ref_entry
                            )
                            if not sub_ref_id or sub_ref_id not in items_by_id:
                                continue
                            sub_ref_item = items_by_id[sub_ref_id]
                            _extend_unique(
                                refs, list(sub_ref_item.data.get(target_field, []) or [])
                            )

    return refs


def effective_references(
    item: ItemView,
    target_field: str,
    items_by_id: dict[str, ItemView],
    config: Config,
) -> list[str]:
    """Compute effective values for a reference field, including inherited refs."""
    return list(
        dict.fromkeys(
            _collect_inherited_reference_values(item, target_field, items_by_id, config)
        )
    )
