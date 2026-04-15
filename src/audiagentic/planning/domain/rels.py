from __future__ import annotations


def mk_rel(ref: str, seq: int | None = None, display: str | None = None) -> dict:
    out = {'ref': ref}
    if seq is not None:
        out['seq'] = int(seq)
    if display is not None:
        out['display'] = str(display)
    return out
