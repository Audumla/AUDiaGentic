from __future__ import annotations

class Relationships:
    @staticmethod
    def ensure_rel_list(current, ref: str, seq: int | None = None, display: str | None = None):
        current = list(current or [])
        current = [r for r in current if r.get('ref') != ref]
        rel = {'ref': ref}
        if seq is not None:
            rel['seq'] = int(seq)
        if display is not None:
            rel['display'] = display
        current.append(rel)
        current.sort(key=lambda r: (r.get('seq', 999999999), r['ref']))
        return current
