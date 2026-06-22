"""OpenHands provider adapter."""
from __future__ import annotations

from audiagentic.components.providers.adapters._stubs import make_probe_stub

run = make_probe_stub(
    "openhands",
    "openhands",
    message="OpenHands adapter is registered; sandbox execution bridge not wired yet.",
)
