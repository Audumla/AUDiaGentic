from __future__ import annotations

from ...fs.read import parse_markdown
from ...fs.write import dump_markdown
from ..rel_mgr import Relationships


class RelationshipService:
    def __init__(self, api):
        self.api = api

    def append_unique_ref(self, src_id: str, field: str, dst_id: str) -> None:
        item = self.api._find(src_id)
        data, body = parse_markdown(item.path)
        vals = list(data.get(field, []) or [])
        if dst_id in vals:
            return
        vals.append(dst_id)
        data[field] = vals
        dump_markdown(item.path, data, body)

    def merge_rel_refs(self, src_id: str, field: str, dst_ids: list[str]) -> None:
        item = self.api._find(src_id)
        data, body = parse_markdown(item.path)
        current = []
        for entry in data.get(field, []) or []:
            if isinstance(entry, dict):
                current.append(entry)
            elif isinstance(entry, str):
                current.append({"ref": entry})

        seq = max((int(r.get("seq", 0)) for r in current), default=0) + 1000
        for dst_id in dst_ids:
            if any(r.get("ref") == dst_id for r in current):
                continue
            current = Relationships.ensure_rel_list(current, dst_id, seq)
            seq += 1000

        data[field] = current
        dump_markdown(item.path, data, body)
        self.api.index()

    def sync_back_ref(
        self, child_id: str, child_kind: str, parent_kind: str, parent_ids: list[str] | None = None
    ) -> None:
        back_ref_field = self.api.config.back_ref_rule(parent_kind, child_kind)
        if not back_ref_field:
            return

        for parent_id in parent_ids or []:
            try:
                parent = self.api._find(parent_id)
            except KeyError:
                continue
            if parent.kind != parent_kind:
                raise ValueError(f"{parent_kind} '{parent_id}' does not exist")
            self.append_unique_ref(parent_id, back_ref_field, child_id)

    def sync_creation_back_refs(
        self,
        id_: str,
        kind: str,
        frontmatter: dict,
    ) -> None:
        for field in self.api.config.reference_fields(kind):
            parent_ids = self.iter_ref_ids(frontmatter.get(field))
            if not parent_ids:
                continue
            target_kinds = self.api.config.reference_field_targets(field)
            if not target_kinds:
                continue
            self.sync_back_ref(id_, kind, target_kinds[0], parent_ids)

    def sync_relink_back_ref(self, child_id: str, child_kind: str, field: str, parent_id: str) -> None:
        parent_kind = self.api.config.reference_field_targets(field)
        if not parent_kind:
            return
        self.sync_back_ref(child_id, child_kind, parent_kind[0], [parent_id])

    @staticmethod
    def iter_ref_ids(value) -> list[str]:
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

    def child_refs_parent(self, child_item, parent_kind: str, parent_id: str) -> bool:
        field = self.api.config.referenced_by(parent_kind).get(child_item.kind)
        if not field:
            return False
        active_refs = [
            ref
            for ref in self.iter_ref_ids(child_item.data.get(field))
            if ref == parent_id or not self.api.lifecycle.is_terminal(ref)
        ]
        return len(active_refs) == 1 and active_refs[0] == parent_id

    def relink(
        self,
        src_id: str,
        field: str,
        dst_id: str,
        seq: int | None = None,
        display: str | None = None,
    ):
        item = self.api._find(src_id)
        self.api.policy.assert_not_archived(item, "relink")
        data, body = parse_markdown(item.path)
        if field not in self.api.config.reference_fields(item.kind):
            raise ValueError(f"unsupported field {field}")

        field_shape = self.api.config.reference_field_shape(field)
        if field_shape == "scalar_ref_list":
            vals = list(data.get(field, []) or [])
            if dst_id not in vals:
                vals.append(dst_id)
            data[field] = vals
        elif field_shape == "scalar_ref":
            data[field] = dst_id
        elif field_shape == "rel_list":
            data[field] = Relationships.ensure_rel_list(data.get(field), dst_id, seq, display)
        dump_markdown(item.path, data, body)
        self.sync_relink_back_ref(src_id, item.kind, field, dst_id)
        self.api.index()
        return self.api._find(src_id)
