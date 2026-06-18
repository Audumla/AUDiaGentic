"""Plandex provider adapter."""
from __future__ import annotations

from audiagentic.components.optional.providers.adapters._stubs import make_probe_stub

run = make_probe_stub(
    "plandex",
    "plandex",
    "pdx",
    message="Plandex adapter is registered; execution bridge not wired yet.",
)
