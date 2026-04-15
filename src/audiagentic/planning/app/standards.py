from __future__ import annotations

from .api_types import ItemView
from .config import Config


def _collect_refs_from_config(
    item: ItemView,
    items_by_id: dict[str, ItemView],
    config: Config,
    visited: set[str] | None = None,
) -> list[str]:
    """Recursively collect standard_refs based on config-driven inheritance rules.

    Args:
        item: The item to collect refs from
        items_by_id: Cache of all items by ID
        config: Config instance for inheritance rules
        visited: Set of visited item IDs to prevent cycles

    Returns:
        List of standard refs (including inherited)
    """
    if visited is None:
        visited = set()

    item_id = item.data.get("id")
    if item_id in visited:
        return []
    visited.add(item_id)

    refs = list(item.data.get("standard_refs", []) or [])
    inheritance_rules = config.standard_refs_inheritance(item.kind)

    for rule in inheritance_rules:
        field = rule.get("field")
        rule_type = rule.get("type", "direct")

        if rule_type == "direct":
            ref_id = item.data.get(field)
            if ref_id and ref_id in items_by_id:
                ref_item = items_by_id[ref_id]
                refs.extend(ref_item.data.get("standard_refs", []) or [])

        elif rule_type == "recursive":
            ref_list = item.data.get(field, []) or []
            sub_inheritance = rule.get("sub_inheritance", [])

            for ref_entry in ref_list:
                ref_id = ref_entry.get("ref") if isinstance(ref_entry, dict) else ref_id
                if ref_id and ref_id in items_by_id:
                    ref_item = items_by_id[ref_id]

                    for sub_rule in sub_inheritance:
                        sub_field = sub_rule.get("field")
                        sub_type = sub_rule.get("type", "direct")

                        if sub_type == "direct":
                            sub_ref_id = ref_item.data.get(sub_field)
                            if sub_ref_id and sub_ref_id in items_by_id:
                                sub_ref_item = items_by_id[sub_ref_id]
                                refs.extend(sub_ref_item.data.get("standard_refs", []) or [])
                        elif sub_type == "recursive":
                            sub_sub_inheritance = sub_rule.get("sub_inheritance", [])
                            for sub_sub_rule in sub_sub_inheritance:
                                sub_sub_field = sub_sub_rule.get("field")
                                sub_sub_ref_id = ref_item.data.get(sub_sub_field)
                                if sub_sub_ref_id and sub_sub_ref_id in items_by_id:
                                    sub_sub_ref_item = items_by_id[sub_sub_ref_id]
                                    refs.extend(
                                        sub_sub_ref_item.data.get("standard_refs", []) or []
                                    )

    return list(dict.fromkeys(refs))


def effective_standard_refs(
    item: ItemView,
    items_by_id: dict[str, ItemView],
    config: Config | None = None,
) -> list[str]:
    """Compute effective standard_refs for an item, including inherited refs.

    Uses config-driven inheritance rules from planning.yaml.

    Args:
        item: The item to compute refs for
        items_by_id: Cache of all items by ID
        config: Optional Config instance. If None, uses hardcoded fallback.

    Returns:
        List of unique standard refs (own + inherited)
    """
    if config is not None:
        return _collect_refs_from_config(item, items_by_id, config)

    refs = list(item.data.get("standard_refs", []) or [])
    if item.kind == "task":
        spec = items_by_id.get(item.data.get("spec_ref"))
        if spec:
            refs.extend(spec.data.get("standard_refs", []) or [])
        parent = items_by_id.get(item.data.get("parent_task_ref"))
        if parent:
            refs.extend(parent.data.get("standard_refs", []) or [])
    elif item.kind == "wp":
        plan = items_by_id.get(item.data.get("plan_ref"))
        if plan:
            refs.extend(plan.data.get("standard_refs", []) or [])
        for rel in item.data.get("task_refs", []) or []:
            t = items_by_id.get(rel["ref"])
            if t:
                refs.extend(t.data.get("standard_refs", []) or [])
                spec = items_by_id.get(t.data.get("spec_ref"))
                if spec:
                    refs.extend(spec.data.get("standard_refs", []) or [])

    return list(dict.fromkeys(refs))
