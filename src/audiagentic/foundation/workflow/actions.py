"""Generic workflow action executor.

Config-driven placeholder rendering and batch item creation.
"""

from __future__ import annotations

import re

from .interfaces import WorkflowContext

_PLACEHOLDER_RE = re.compile(r"^\{(\w+)\}$")


def render(value, context: dict):
    """Render a placeholder-bearing value against the context.

    Rules:
    - Single placeholder string returns the original typed value
    - Mixed text uses str.format(**context)
    - Lists and dicts render recursively
    - Unknown placeholder raises ValueError
    - Non-string scalars pass through unchanged
    """
    if value is None:
        return None
    if isinstance(value, str):
        match = _PLACEHOLDER_RE.match(value)
        if match:
            key = match.group(1)
            if key not in context:
                raise ValueError(f"unknown placeholder '{{{key}}}'")
            return context[key]
        try:
            return value.format(**context)
        except KeyError as e:
            raise ValueError(f"unknown placeholder {e} in '{value}'") from e
    if isinstance(value, list):
        return [render(v, context) for v in value]
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    return value


class WorkflowActionExecutor:
    """Generic executor for config-driven workflow actions."""

    def __init__(self, ctx: WorkflowContext):
        self.ctx = ctx

    def execute(self, action_name: str, context: dict) -> dict:
        action = self.ctx.config.workflow_action(action_name)

        defaults = action.get("defaults", {})
        full_context = dict(context)
        for param, default_value in defaults.items():
            key = f"{param}_or_default"
            if param in context and context[param] is not None:
                full_context[key] = context[param]
            else:
                full_context[key] = default_value

        creates = action.get("creates", {})
        if not creates:
            raise ValueError(f"workflow action '{action_name}' has no creates config")

        created: dict[str, object] = {}
        for create_key, spec in creates.items():
            local_context = dict(full_context)
            for prior_key, prior_item in created.items():
                local_context[f"{prior_key}_id"] = prior_item.data["id"]

            kind = render(spec["kind"], local_context)
            label = render(spec.get("label"), local_context)
            summary = render(spec.get("summary"), local_context)
            domain = render(spec.get("domain"), local_context)
            workflow = render(spec.get("workflow"), local_context)
            refs = render(spec.get("refs", {}), local_context) or {}
            fields = render(spec.get("fields", {}), local_context) or None

            item = self.ctx.new(
                kind=kind,
                label=label,
                summary=summary,
                domain=domain,
                workflow=workflow,
                refs=refs,
                fields=fields,
                check_duplicates=spec.get("check_duplicates", True),
            )
            created[create_key] = item

        updates = action.get("updates", [])
        if isinstance(updates, dict):
            updates = list(updates.values())
        for update_spec in updates:
            self._apply_update(update_spec, full_context, created)

        result_keys = action.get("result_keys", {})
        if not result_keys:
            return created
        return {k: created[v] for k, v in result_keys.items()}

    def _apply_update(self, spec: dict, context: dict, created: dict) -> None:
        local_context = dict(context)
        for prior_key, prior_item in created.items():
            local_context[f"{prior_key}_id"] = prior_item.data["id"]

        target_id = render(spec.get("target"), local_context)
        ref_field = render(spec.get("ref_field"), local_context)
        child_id_from = spec.get("child_id_from")

        if not target_id or not ref_field or not child_id_from:
            raise ValueError("workflow update requires 'target', 'ref_field', and 'child_id_from'")
        if child_id_from not in created:
            raise ValueError(
                f"workflow update child_id_from '{child_id_from}' is not a created key"
            )

        child_id = created[child_id_from].data["id"]
        self.ctx.relink(target_id, ref_field, child_id)
