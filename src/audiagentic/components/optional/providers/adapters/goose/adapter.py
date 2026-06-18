"""Goose provider adapter."""
from __future__ import annotations

from audiagentic.components.optional.providers.adapters._stubs import make_probe_stub

run = make_probe_stub(
    "goose",
    "goose",
    message="Goose adapter is registered; execution bridge not wired yet.",
)
