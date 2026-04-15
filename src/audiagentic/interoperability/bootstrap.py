"""Bootstrap code formatter integration with event bus.

This module provides opt-in registration of the CodeFormatter as an event subscriber.
The formatter must be explicitly set up by calling setup_code_formatter() - it does
not subscribe automatically at import time.

Standard: standard-0011 (Component architecture standard, rule #28)
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import get_bus
from .formatters import CodeFormatter

logger = logging.getLogger(__name__)


def setup_code_formatter(project_root: Path | None = None) -> CodeFormatter:
    """Setup automatic code formatting on task completion.

    This is an OPT-IN function. The code formatter will NOT subscribe to events
    unless this function is explicitly called. This follows the component
    architecture standard where event subscriptions must be explicit and opt-in.

    Args:
        project_root: Path to project root (defaults to current directory)

    Returns:
        CodeFormatter instance with event subscription registered

    Standard: standard-0011 (Component architecture standard, rule #28)
    """
    if project_root is None:
        project_root = Path.cwd()

    formatter = CodeFormatter(project_root=project_root)

    # Subscribe to planning.item.state.changed events (opt-in)
    bus = get_bus()
    bus.subscribe("planning.item.state.changed", formatter.handle_task_done)

    logger.info("Code formatter registered with event bus")
    return formatter
