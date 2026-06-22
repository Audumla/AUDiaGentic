"""Aider provider adapter."""
from __future__ import annotations

from audiagentic.components.providers.adapters._stubs import make_probe_stub

run = make_probe_stub(
    "aider",
    "aider",
    message="Aider adapter is registered; execution bridge not wired yet.",
)
