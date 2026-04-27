from __future__ import annotations

import json
import warnings
from pathlib import Path

from ...fs.read import parse_markdown
from ..api_types import ItemView


class ItemReaderService:
    def __init__(self, api):
        self.api = api

    def lookup_index_path(self) -> Path:
        return self.api.root / ".audiagentic/planning/indexes/lookup.json"

    def load_lookup_index(self) -> dict[str, dict]:
        path = self.lookup_index_path()
        if not path.exists():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("items", {})

    def item_to_head(self, item: ItemView) -> dict[str, object]:
        return {
            "id": item.data["id"],
            "kind": item.kind,
            "label": item.data["label"],
            "state": item.data["state"],
            "path": item.path.relative_to(self.api.root).as_posix(),
            "deleted": self.api.config.is_soft_deleted(item.data),
        }

    def normalize_id(self, id_: str) -> str:
        return id_

    def find_similar_ids(self, id_: str) -> list[str]:
        parts = id_.split("-", 1)
        if len(parts) != 2:
            return []

        kind, num_part = parts
        target_num = None
        try:
            target_num = int(num_part.split("-")[0])
        except ValueError:
            pass

        similar = []
        for item in self.api._scan():
            if item.kind == kind and not self.api.config.is_soft_deleted(item.data):
                similar.append(item.data["id"])

        def extract_num(id_str: str) -> int:
            try:
                return int(id_str.split("-")[1].split("-")[0])
            except (IndexError, ValueError):
                return 0

        if target_num is not None:
            similar.sort(key=lambda x: (abs(extract_num(x) - target_num), extract_num(x)))
        else:
            similar.sort(key=extract_num)
        return similar[:10]

    def fallback_scan_item(self, id_: str) -> ItemView:
        for item in self.api._scan():
            if item.data["id"] == id_:
                return item

        normalized = self.normalize_id(id_)
        if normalized != id_:
            for item in self.api._scan():
                if item.data["id"] == normalized:
                    return item

        similar = self.find_similar_ids(id_)
        if similar:
            msg = f"{id_} not found (tried {normalized if normalized != id_ else 'exact match'}). "
            msg += f"Closest: {similar[0]}. "
            msg += f"Available {len(similar)} items: {', '.join(similar[:5])}"
            if len(similar) > 5:
                msg += f" and {len(similar) - 5} more"
            msg += ". Use tm_list with the relevant kind to see all matching items"
            raise ValueError(msg)

        raise ValueError(
            f"{id_} not found (no items of this kind). Use tm_list to discover available items"
        )

    def lookup(self, id_: str) -> ItemView:
        try:
            entry = self.load_lookup_index().get(id_)
        except FileNotFoundError:
            warnings.warn(
                "lookup.json is missing; falling back to scan_items()",
                RuntimeWarning,
                stacklevel=2,
            )
            return self.fallback_scan_item(id_)

        if entry:
            path = self.api.root / Path(entry["path"])
            if path.exists():
                data, body = parse_markdown(path)
                return ItemView(entry["kind"], path, data, body)

        normalized = self.normalize_id(id_)
        if normalized != id_:
            try:
                entry = self.load_lookup_index().get(normalized)
                if entry:
                    path = self.api.root / Path(entry["path"])
                    if path.exists():
                        data, body = parse_markdown(path)
                        return ItemView(entry["kind"], path, data, body)
            except FileNotFoundError:
                pass

        return self.fallback_scan_item(id_)

    def head(self, id_: str) -> dict[str, object]:
        try:
            entry = self.load_lookup_index().get(id_)
        except FileNotFoundError:
            warnings.warn(
                "lookup.json is missing; falling back to scan_items()",
                RuntimeWarning,
                stacklevel=2,
            )
            return self.item_to_head(self.fallback_scan_item(id_))

        if entry:
            return dict(entry)

        return self.item_to_head(self.fallback_scan_item(id_))

    def find(self, id_: str):
        try:
            return self.lookup(id_)
        except ValueError as exc:
            raise KeyError(id_) from exc
