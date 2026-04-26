from __future__ import annotations

import json
from pathlib import Path

from ..fs.scan import scan_items
from .claims import Claims
from .config import Config
from .util import now_iso


class Indexer:
    def __init__(self, root: Path, test_mode: bool = False):
        self.root = root
        self.test_mode = test_mode
        self.config = Config(root)

    def write_indexes(self):
        items = scan_items(self.root)
        by_kind = {}
        lookup = {}
        for item in items:
            rel_path = item.path.relative_to(self.root).as_posix()
            by_kind.setdefault(item.kind, []).append(
                {
                    "id": item.data["id"],
                    "label": item.data["label"],
                    "state": item.data["state"],
                    "path": str(item.path.relative_to(self.root)),
                }
            )
            lookup[item.data["id"]] = {
                "id": item.data["id"],
                "kind": item.kind,
                "label": item.data["label"],
                "state": item.data["state"],
                "path": rel_path,
                "deleted": bool(item.data.get("deleted", False)),
                "archived": self.config.state_in_set(
                    item.kind,
                    item.data.get("state"),
                    "terminal",
                    item.data.get("workflow"),
                ),
            }
        if self.test_mode:
            idx_root = self.root / "test" / ".audiagentic/planning/indexes"
        else:
            idx_root = self.root / ".audiagentic/planning/indexes"
        idx_root.mkdir(parents=True, exist_ok=True)
        meta = {"convention_version": 1, "generated_at": now_iso()}
        for kind in self.config.all_kinds():
            name = self.config.kind_dir_name(kind)
            payload = {**meta, "items": by_kind.get(kind, [])}
            (idx_root / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (idx_root / "lookup.json").write_text(
            json.dumps({**meta, "items": lookup}, indent=2),
            encoding="utf-8",
        )
        trace = {**meta, "refs": []}
        for item in items:
            for field in self.config.reference_fields(item.kind):
                shape = self.config.reference_field_shape(field)
                if shape == "scalar_ref":
                    if item.data.get(field):
                        trace["refs"].append(
                            {"src": item.data["id"], "dst": item.data[field], "field": field}
                        )
                elif shape == "scalar_ref_list":
                    for ref in item.data.get(field, []) or []:
                        trace["refs"].append({"src": item.data["id"], "dst": ref, "field": field})
                elif shape == "rel_list":
                    for rel in item.data.get(field, []) or []:
                        trace["refs"].append(
                            {
                                "src": item.data["id"],
                                "dst": rel["ref"],
                                "field": field,
                                "seq": rel.get("seq"),
                                "display": rel.get("display"),
                            }
                        )
        (idx_root / "trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
        if self.test_mode:
            claims_path = self.root / "test" / ".audiagentic/planning/claims/claims.json"
        else:
            claims_path = self.root / ".audiagentic/planning/claims/claims.json"
        claims = Claims(claims_path).load()["claims"]
        claimed = {c["id"]: c for c in claims}
        readiness = {**meta, "items": []}
        for item in items:
            readiness["items"].append(
                {
                    "id": item.data["id"],
                    "kind": item.kind,
                    "state": item.data["state"],
                    "claimed": item.data["id"] in claimed,
                }
            )
        (idx_root / "readiness.json").write_text(json.dumps(readiness, indent=2), encoding="utf-8")
        (idx_root / "claims.json").write_text(
            json.dumps({**meta, "claims": claims}, indent=2), encoding="utf-8"
        )
        # Preserve dispatch registry if it exists; do not overwrite (it is append-only via event)
        dispatch_path = idx_root / "dispatch.json"
        if not dispatch_path.exists():
            dispatch_path.write_text(
                json.dumps({**meta, "entries": []}, indent=2), encoding="utf-8"
            )
