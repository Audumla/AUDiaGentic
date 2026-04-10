from __future__ import annotations
from .api_types import ItemView

def effective_standard_refs(item: ItemView, items_by_id: dict[str, ItemView]) -> list[str]:
    refs = list(item.data.get('standard_refs', []) or [])
    if item.kind == 'task':
        spec = items_by_id.get(item.data.get('spec_ref'))
        if spec:
            refs.extend(spec.data.get('standard_refs', []) or [])
        parent = items_by_id.get(item.data.get('parent_task_ref'))
        if parent:
            refs.extend(parent.data.get('standard_refs', []) or [])
    elif item.kind == 'wp':
        plan = items_by_id.get(item.data.get('plan_ref'))
        if plan:
            refs.extend(plan.data.get('standard_refs', []) or [])
        for rel in item.data.get('task_refs', []) or []:
            t = items_by_id.get(rel['ref'])
            if t:
                refs.extend(t.data.get('standard_refs', []) or [])
                spec = items_by_id.get(t.data.get('spec_ref'))
                if spec:
                    refs.extend(spec.data.get('standard_refs', []) or [])
    out = []
    for r in refs:
        if r not in out:
            out.append(r)
    return out
