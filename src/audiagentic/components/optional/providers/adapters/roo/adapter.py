"""Roo Code provider adapter."""

from __future__ import annotations

from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    raise AudiaGenticError(
        code="PRV-VALIDATION-030",
        kind="validation",
        message="Roo Code is a VS Code extension provider and has no CLI execution adapter",
        details={"provider-id": "roo"},
    )
