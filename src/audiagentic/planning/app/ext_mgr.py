from __future__ import annotations

import json
from pathlib import Path

import yaml

from .api_types import ItemView


class Extracts:
    def __init__(self, root: Path, api_getter=None):
        self.root = root
        self.api_getter = api_getter

    def _api(self):
        if self.api_getter is None:
            raise RuntimeError("Extracts requires api_getter for lookup-backed reads")
        return self.api_getter()

    def _resolve_related_item(self, id_: str | None, cache: dict[str, ItemView]) -> ItemView | None:
        if not id_ or id_ == "None":
            return None
        if id_ not in cache:
            cache[id_] = self._api().lookup(id_)
        return cache[id_]

    def _effective_standard_refs(self, item: ItemView) -> list[str]:
        refs = list(item.data.get("standard_refs", []) or [])
        cache = {item.data["id"]: item}

        if item.kind == "task":
            spec = self._resolve_related_item(item.data.get("spec_ref"), cache)
            if spec:
                refs.extend(spec.data.get("standard_refs", []) or [])
            parent = self._resolve_related_item(item.data.get("parent_task_ref"), cache)
            if parent:
                refs.extend(parent.data.get("standard_refs", []) or [])
        elif item.kind == "wp":
            plan = self._resolve_related_item(item.data.get("plan_ref"), cache)
            if plan:
                refs.extend(plan.data.get("standard_refs", []) or [])
            for rel in item.data.get("task_refs", []) or []:
                task = self._resolve_related_item(rel.get("ref"), cache)
                if task:
                    refs.extend(task.data.get("standard_refs", []) or [])
                    spec = self._resolve_related_item(task.data.get("spec_ref"), cache)
                    if spec:
                        refs.extend(spec.data.get("standard_refs", []) or [])

        out = []
        for ref in refs:
            if ref not in out:
                out.append(ref)
        return out

    def show(self, id_: str) -> dict:
        item = self._api().lookup(id_)
        out = dict(item.data)
        out["kind"] = item.kind
        out["path"] = item.path.relative_to(self.root).as_posix()
        for field in (
            "archived_at",
            "archived_by",
            "archive_reason",
            "restored_at",
            "restored_by",
        ):
            out.setdefault(field, None)
        return out

    def extract(
        self,
        id_: str,
        with_related: bool = False,
        with_resources: bool = False,
        include_body: bool = True,
        write_to_disk: bool = True,
    ) -> dict:
        item = self._api().lookup(id_)
        out = {
            "item": self.show(id_),
            "effective_standard_refs": self._effective_standard_refs(item),
        }
        if include_body:
            out["body"] = item.body
        if with_related:
            rel = {}
            for field in [
                "request_refs",
                "spec_refs",
                "task_refs",
                "work_package_refs",
                "plan_ref",
                "spec_ref",
                "parent_task_ref",
            ]:
                if field in item.data:
                    rel[field] = item.data[field]
            out["related"] = rel
        if with_resources:
            attach_dir = self.root / "docs/planning/attachments" / id_
            if attach_dir.exists():
                out["attachments"] = [
                    str(p.relative_to(self.root))
                    for p in sorted(attach_dir.rglob("*"))
                    if p.is_file()
                ]
        if write_to_disk:
            ep = self.root / ".audiagentic/planning/extracts" / f"{id_}.json"
            ep.parent.mkdir(parents=True, exist_ok=True)
            ep.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    def owner(self, path_fragment: str) -> list[dict]:
        owners = []
        attach_root = self.root / "docs/planning/attachments"
        if not attach_root.exists():
            return owners
        for amap in sorted(attach_root.glob("*/resource-map.yaml")):
            data = yaml.safe_load(amap.read_text(encoding="utf-8")) or {}
            for key in ["owned", "related", "tests", "schemas"]:
                for p in data.get(key, []) or []:
                    if path_fragment in p:
                        owners.append({"owner": data.get("owner"), "type": key, "path": p})
        return owners
