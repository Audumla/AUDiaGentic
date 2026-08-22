"""Codex model identifiers shared by CLI and ACP launch paths.

The ``codex-acp`` bridge accepts a model selection as ``model[effort]``.  Keep
that provider-specific spelling at the AUDiaGentic boundary, then pass the
base model and effort through the native Codex configuration mechanisms.
"""

from __future__ import annotations

import re

_MODEL_ID_RE = re.compile(r"^(?P<model>[^\[\]]+?)(?:\[(?P<effort>[^\[\]]+)\])?$")


def split_model_selection(model_id: str | None) -> tuple[str | None, str | None]:
    """Return ``(base_model, reasoning_effort)`` from a Codex model id.

    Unqualified model ids remain valid and simply return ``(model, None)``.
    Invalid bracket syntax is rejected early so an execution profile cannot
    silently select a different model than the one it advertises.
    """

    if model_id is None:
        return None, None
    value = str(model_id).strip()
    if not value:
        return None, None
    match = _MODEL_ID_RE.fullmatch(value)
    if match is None:
        raise ValueError(
            "Codex model id must be '<model>' or '<model>[<reasoning-effort>]'"
        )
    model = match.group("model").strip()
    effort = match.group("effort")
    if effort is not None:
        effort = effort.strip()
        if not effort:
            raise ValueError("Codex reasoning effort cannot be empty")
    return model, effort


__all__ = ["split_model_selection"]
