"""Public application boundary for agent-jobs operational queries."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.event_overview import (
    event_jobs_overview as _event_jobs_overview,
)


def event_jobs_overview(project_root: Path) -> dict[str, Any]:
    """Return the redacted, read-only event-jobs operational overview."""
    return _event_jobs_overview(project_root)
