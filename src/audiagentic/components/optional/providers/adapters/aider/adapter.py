"""Aider provider adapter."""

from __future__ import annotations

import shutil
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def _aider_executable() -> str:
    executable = shutil.which("aider")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-030",
            kind="external",
            message="aider command is not available on PATH",
            details={"provider-id": "aider"},
        )
    return executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider-id": "aider",
        "status": "stubbed",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": provider_cfg.get("default-model"),
        "executable": _aider_executable(),
        "output": "Aider adapter is registered; execution bridge not wired yet.",
    }
