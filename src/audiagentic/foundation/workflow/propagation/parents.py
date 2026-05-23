"""Parent/child resolution helpers — generic, ctx-only."""

from __future__ import annotations

from typing import Any

from ..util import extract_ref_ids


def find_parents(
    ctx: Any, item_id: str, parent_kind: str | None, parent_field: str | None
) -> list[tuple[str, str]]:
    """Resolve parent items for ``item_id``.

    Direct refs on the child win; otherwise we scan for parents that ref the child.
    """
    if not parent_kind or not parent_field:
        return []
    view = ctx.lookup(item_id)
    if not view or not view.data:
        return []
    direct = [(pid, parent_kind) for pid in extract_ref_ids(view.data.get(parent_field))]
    if direct:
        return direct
    return _find_reverse_parents(ctx, item_id, parent_kind, parent_field)


def _find_reverse_parents(
    ctx: Any, item_id: str, parent_kind: str, parent_field: str
) -> list[tuple[str, str]]:
    parents: list[tuple[str, str]] = []
    for view in ctx._scan():
        if getattr(view, "kind", None) != parent_kind:
            continue
        if item_id in extract_ref_ids(view.data.get(parent_field, [])):
            parents.append((view.data["id"], parent_kind))
    return parents


def linked_child_ids(
    ctx: Any, parent_id: str, parent_kind: str, child_kind: str, parent_field: str
) -> list[str]:
    """Resolve all child IDs linked to a parent across direct and reverse ref styles."""
    seen: set[str] = set()
    out: list[str] = []

    parent_view = ctx.lookup(parent_id)
    if parent_view and parent_view.data:
        for cid in extract_ref_ids(parent_view.data.get(parent_field, [])):
            cv = ctx.lookup(cid)
            if not cv or not cv.data:
                continue
            k = getattr(cv, "kind", None) or cv.data.get("kind")
            if k != child_kind or cid in seen:
                continue
            seen.add(cid)
            out.append(cid)

    for view in ctx._scan():
        k = getattr(view, "kind", None) or view.data.get("kind")
        if k != child_kind:
            continue
        cid = view.data.get("id")
        if not cid or cid in seen:
            continue
        if parent_id not in extract_ref_ids(view.data.get(parent_field)):
            continue
        seen.add(cid)
        out.append(cid)

    return out
