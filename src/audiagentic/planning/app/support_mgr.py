from __future__ import annotations

"""Supporting-doc access for structured sidecar docs.

These docs are intentionally treated as sidecar documentation surfaces in this phase.
They are discoverable and queryable, but they are not first-class planning kinds
in the core scan/index/validator model.
"""

from pathlib import Path
import yaml


class SupportingDocsManager:
    def __init__(self, root: Path):
        self.root = root
        self.support_root = root / "docs" / "planning" / "supporting"

    def _iter(self):
        if not self.support_root.exists():
            return []
        rows = []
        for p in sorted(self.support_root.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            try:
                _, fm, _ = text.split("---", 2)
            except ValueError:
                continue
            rows.append((p, yaml.safe_load(fm) or {}))
        return rows

    def list_support_docs(
        self, supports_id: str | None = None, role: str | None = None
    ):
        out = []
        for p, data in self._iter():
            if supports_id and supports_id not in data.get("supports", []):
                continue
            if role and data.get("role") != role:
                continue
            out.append(
                {
                    "id": data.get("id"),
                    "label": data.get("label"),
                    "role": data.get("role"),
                    "supports": data.get("supports", []),
                    "status": data.get("status"),
                    "owner": data.get("owner"),
                    "used_by": data.get("used_by", []),
                    "path": str(p.relative_to(self.root)),
                }
            )
        return out

