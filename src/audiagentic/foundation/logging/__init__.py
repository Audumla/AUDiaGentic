"""AUDiaGentic foundation logging package.

Public API
----------
configure_logging(project_root)   — configure stdlib logging (idempotent)
bootstrap(component_id, ...)      — configure + mint correlation ID (entry points)
get_ai_audit_logger()             — AI communication audit logger singleton
load_logging_config(project_root) — load merged LoggingConfig dataclass
reset_logging_for_test()          — full state reset for test isolation

Correlation ID helpers re-exported for convenience:
new_correlation_id, get_correlation_id, set_correlation_id, reset_correlation_id
"""
from pathlib import Path

from audiagentic.foundation.logging.audit import get_ai_audit_logger
from audiagentic.foundation.logging.config import (
    configure_logging,
    load_logging_config,
    reset_logging_for_test,
)
from audiagentic.foundation.logging.context import (
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)


def bootstrap(
    component_id: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Configure logging and mint a correlation ID for this process.

    Drop-in first line for every MCP server ``if __name__ == "__main__"`` block
    and for ``launcher.py:main()``. The returned ID is already active in
    contextvars, so the CorrelationJsonFormatter injects it into every
    subsequent log line automatically — callers may log it but need not thread
    it further.

    Args:
        component_id: Name of the component or process (reserved for future
            per-component log files; currently informational).
        project_root: Project root. When None, resolved from
            AUDIAGENTIC_REPO_ROOT env var or CWD walk.

    Returns:
        The newly minted correlation ID string.
    """
    configure_logging(project_root=project_root)
    return new_correlation_id()

__all__ = [
    "bootstrap",
    "configure_logging",
    "get_ai_audit_logger",
    "get_correlation_id",
    "load_logging_config",
    "new_correlation_id",
    "reset_correlation_id",
    "reset_logging_for_test",
    "set_correlation_id",
]
