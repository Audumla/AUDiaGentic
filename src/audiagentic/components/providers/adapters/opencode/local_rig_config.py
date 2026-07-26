"""OpenCode-specific config shape for the local embedded rig connection."""
from __future__ import annotations

from typing import Any


def build_provider_config(
    *,
    provider_id: str,
    rig_port: int,
    api_key: str,
    model_name: str,
    model_profile: dict[str, Any],
) -> dict[str, Any]:
    agent = model_profile.get("agent", {}) if isinstance(model_profile, dict) else {}
    context_size = int(agent.get("context_size", 131072))
    return {
        "providers": {
            provider_id: {
                "name": provider_id,
                "api": "openai",
                "baseURL": f"http://127.0.0.1:{rig_port}/v1",
                "apiKey": api_key,
                "models": {
                    model_name: {
                        "contextWindow": context_size,
                        "maxTokens": int(agent.get("max_tokens", 4096)),
                        "cost": {"input": 0, "output": 0},
                    }
                },
            }
        }
    }


__all__ = ["build_provider_config"]
