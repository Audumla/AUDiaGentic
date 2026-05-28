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
from audiagentic.foundation.logging.audit import get_ai_audit_logger
from audiagentic.foundation.logging.bootstrap import bootstrap
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
