"""Local OpenAI-compatible provider adapter."""
from __future__ import annotations

from typing import Any


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    provider_id = packet_ctx.get("provider-id") or "local-openai"
    return {
        "provider-id": provider_id,
        "status": "ok",
        "model": provider_cfg.get("default-model"),
        "output": "stubbed-response",
    }
