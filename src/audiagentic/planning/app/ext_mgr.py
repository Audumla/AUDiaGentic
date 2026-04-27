from __future__ import annotations

import json
from pathlib import Path

import yaml

from .api_types import ItemView
from .reference_inheritance import effective_references


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

    def _effective_default_refs(self, item: ItemView) -> list[str]:
        api = self._api()
        items_by_id = {entry.data["id"]: entry for entry in api._scan()}
        items_by_id[item.data["id"]] = item
        return effective_references(item, api.config.default_reference_field(), items_by_id, api.config)

    def _attachments_root(self) -> Path:
        api = self._api()
        return self.root / api.config.attachments_dir()

    def show(self, id_: str) -> dict:
        item = self._api().lookup(id_)
        out = dict(item.data)
        out["kind"] = item.kind
        out["path"] = item.path.relative_to(self.root).as_posix()
        for field in self._api().config.lifecycle_metadata_fields():
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
            "effective_refs": self._effective_default_refs(item),
        }
        if include_body:
            out["body"] = item.body
        if with_related:
            rel = {}
            for field in self._api().config.reference_fields(item.kind):
                if field in item.data:
                    rel[field] = item.data[field]
            out["related"] = rel
        if with_resources:
            attach_dir = self._attachments_root() / id_
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
        attach_root = self._attachments_root()
        if not attach_root.exists():
            return owners
        for amap in sorted(attach_root.glob("*/resource-map.yaml")):
            data = yaml.safe_load(amap.read_text(encoding="utf-8")) or {}
            for key in ["owned", "related", "tests", "schemas"]:
                for p in data.get(key, []) or []:
                    if path_fragment in p:
                        owners.append({"owner": data.get("owner"), "type": key, "path": p})
        return owners
