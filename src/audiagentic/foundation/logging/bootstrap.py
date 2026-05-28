"""Bootstrap helper for AUDiaGentic process entry points.

Drop-in first line for every MCP server ``if __name__ == "__main__"`` block
and for launcher.py:main(). Configures logging and mints a correlation ID in
one call.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.logging.config import configure_logging
from audiagentic.foundation.logging.context import new_correlation_id


def bootstrap(
    component_id: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Configure logging and mint a correlation ID for this process.

    Sets the correlation ID in the current context and returns it.
    The returned ID is already active in contextvars — callers can include it
    in the startup log line but do not need to pass it further. The
    CorrelationJsonFormatter injects it into every subsequent log line
    automatically.

    Args:
        component_id: Name of the component or process (used in future for
            per-component log files; currently informational).
        project_root: Project root directory. When None, resolved from
            AUDIAGENTIC_REPO_ROOT env var or CWD walk.

    Returns:
        The newly minted correlation ID string.
    """
    configure_logging(project_root=project_root)
    return new_correlation_id()
