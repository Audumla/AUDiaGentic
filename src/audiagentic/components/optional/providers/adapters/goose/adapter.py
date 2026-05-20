"""Goose provider adapter."""

from __future__ import annotations

import shutil
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def _goose_executable() -> str:
    executable = shutil.which("goose")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-031",
            kind="external",
            message="goose command is not available on PATH",
            details={"provider-id": "goose"},
        )
    return executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider-id": "goose",
        "status": "stubbed",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": provider_cfg.get("default-model"),
        "executable": _goose_executable(),
        "output": "Goose adapter is registered; execution bridge not wired yet.",
    }
