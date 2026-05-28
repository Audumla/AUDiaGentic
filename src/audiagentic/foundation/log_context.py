"""Shim — re-exports from foundation.logging.context.

Retained for backwards compatibility during the migration. Remove once all
internal call sites reference foundation.logging directly.
"""
from audiagentic.foundation.logging.context import (  # noqa: F401
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
