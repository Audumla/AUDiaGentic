"""Copilot provider adapter."""
from __future__ import annotations

from typing import Any


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider-id": "copilot",
        "status": "ok",
        "model": provider_cfg.get("default-model"),
        "output": "stubbed-response",
    }
