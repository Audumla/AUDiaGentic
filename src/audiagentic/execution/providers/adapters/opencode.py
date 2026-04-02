"""opencode provider adapter.

This provider is scaffolded for wrapper-first prompt launch support.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def run(packet_ctx: Mapping[str, Any], provider_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Execute an opencode provider request.

    The adapter is intentionally thin at this stage; it provides a stable seam
    for the wrapper-first provider integration and test scaffolding.
    """

    provider_id = str(packet_ctx.get("provider-id") or "opencode")
    cwd = packet_ctx.get("cwd") or provider_cfg.get("cwd") or "."
    return {
        "provider-id": provider_id,
        "provider": "opencode",
        "cwd": str(Path(cwd)),
        "status": "scaffolded",
        "stdout": "",
        "stderr": "",
    }
