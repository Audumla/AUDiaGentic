"""Goose provider adapter."""

from __future__ import annotations

from typing import Any

from audiagentic.components.optional.providers.adapters.cli import require_executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider-id": "goose",
        "status": "stubbed",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": provider_cfg.get("default-model"),
        "executable": require_executable("goose", "goose"),
        "output": "Goose adapter is registered; execution bridge not wired yet.",
    }
