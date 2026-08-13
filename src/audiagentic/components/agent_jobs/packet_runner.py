"""Packet runner for MVP jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.providers_api import list_canonical_provider_ids
from audiagentic.foundation.contracts.canonical_ids import validate_ids
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _validate_provider_id(provider_id: str) -> None:
    issues = validate_ids([provider_id], list_canonical_provider_ids())
    if issues:
        raise AudiaGenticError(
            code="VAL-RUN-001",
            kind="agent-jobs",
            message="provider-id is not canonical",
            details={"issues": issues},
        )


def run_packet(
    project_root: Path,
    *,
    packet_id: str,
    project_id: str,
    provider_id: str,
    workflow_profile: str,
    context_id: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a packet through the canonical Agents Work API."""
    if not provider_id:
        raise AudiaGenticError(
            code="VAL-RUN-002",
            kind="agent-jobs",
            message="provider-id is required",
            details={},
        )
    _validate_provider_id(provider_id)

    from audiagentic.components.agents.work.work_api import submit_packet

    return submit_packet(
        project_root,
        context_id=context_id,
        packet_id=packet_id,
        text=(
            f"Execute packet {packet_id} for project {project_id} "
            f"using provider {provider_id} and workflow profile {workflow_profile}."
        ),
        metadata={
            "project-id": project_id,
            "provider-id": provider_id,
            "workflow-profile": workflow_profile,
            **(overrides or {}),
        },
    )
