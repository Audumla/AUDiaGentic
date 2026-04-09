from __future__ import annotations

from pathlib import Path


class ReferencesManager:
    """Manage docs/references discovery."""

    def __init__(self, root: Path):
        self.root = root
        self.references_root = root / "docs" / "references"

    def list_reference_docs(self) -> list[dict[str, str]]:
        out = []
        if not self.references_root.exists():
            return out
        for p in sorted(self.references_root.rglob("*.md")):
            out.append({"path": str(p.relative_to(self.root)), "label": p.stem})
        return out

