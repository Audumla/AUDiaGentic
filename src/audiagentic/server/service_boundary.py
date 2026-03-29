"""Optional server seam foundation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.jobs.packet_runner import run_packet


class CoreServiceBoundary:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run_job(
        self,
        request: dict[str, Any],
        *,
        now_fn: Callable[[], str] | None = None,
        stage_handler: Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None], dict[str, Any]]
        | None = None,
    ) -> dict[str, Any]:
        required = {"packet-id", "project-id", "provider-id", "workflow-profile"}
        missing = sorted(required - set(request.keys()))
        if missing:
            raise AudiaGenticError(
                code="JOB-VALIDATION-023",
                kind="validation",
                message="job request missing required fields",
                details={"missing": missing},
            )
        return run_packet(
            self.project_root,
            packet_id=request["packet-id"],
            project_id=request["project-id"],
            provider_id=request["provider-id"],
            workflow_profile=request["workflow-profile"],
            job_id=request.get("job-id"),
            now_fn=now_fn,
            stage_handler=stage_handler,
        )

    def get_release_status(self) -> dict[str, Any]:
        path = self.project_root / "docs" / "releases" / "CURRENT_RELEASE.md"
        return {"current-release": path.read_text(encoding="utf-8") if path.exists() else ""}
