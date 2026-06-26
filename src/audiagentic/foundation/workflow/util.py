from __future__ import annotations

import re
from typing import Any

from audiagentic.foundation.time import now_iso


class Relationships:
    _DEFAULT_SEQ = 999_999_999

    @staticmethod
    def ensure_rel_list(current, ref: str, seq: int | None = None, display: str | None = None):
        current = [r for r in current or [] if r.get("ref") != ref]
        rel = {"ref": ref}
        if seq is not None:
            rel["seq"] = int(seq)
        if display is not None:
            rel["display"] = display
        current.append(rel)
        current.sort(key=lambda r: (r.get("seq", 999_999_999), r["ref"]))
        return current

__all__ = ["Relationships", "body_has_section", "extract_ref_ids", "now_iso", "slugify"]


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip()).strip("-")
    return s if s else "item"


def body_has_section(body: str, section: str) -> bool:
    return f"# {section}" in body or f"## {section}" in body


def extract_ref_ids(value: Any) -> list[str]:
    """Normalise scalar/list/dict reference values into plain item IDs."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        ref = value.get("ref")
        return [ref] if isinstance(ref, str) and ref else []
    if isinstance(value, list):
        ids: list[str] = []
        for v in value:
            ids.extend(extract_ref_ids(v))
        return ids
    return []
