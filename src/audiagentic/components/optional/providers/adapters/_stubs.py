"""Shared stub adapter builders.

Each provider adapter file must keep its own ``adapter.py`` so the loader can
resolve ``audiagentic.components.optional.providers.adapters.<id>.adapter``.
These helpers remove the duplicated *bodies* while keeping the dispatch seam.
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.optional.providers.adapters.cli import require_executable


def make_probe_stub(
    provider_id: str,
    *aliases: str,
    message: str,
    access_mode_default: str = "cli",
):
    """Return a ``run`` callable that probes for an executable and reports stubbed."""

    def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider-id": provider_id,
            "status": "stubbed",
            "execution-mode": provider_cfg.get("access-mode", access_mode_default),
            "model": provider_cfg.get("default-model"),
            "executable": require_executable(provider_id, *aliases),
            "output": message,
        }

    return run


def make_ok_stub(
    default_provider_id: str,
    *,
    derive_id_from_ctx: bool = False,
):
    """Return a ``run`` callable that reports ok without probing an executable."""

    def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
        pid = (
            (packet_ctx.get("provider-id") or default_provider_id)
            if derive_id_from_ctx
            else default_provider_id
        )
        return {
            "provider-id": pid,
            "status": "ok",
            "model": provider_cfg.get("default-model"),
            "output": "stubbed-response",
        }

    return run
