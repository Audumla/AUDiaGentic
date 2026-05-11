"""Bootstrap code formatter integration with event bus.

Opt-in registration of the CodeFormatter as an event subscriber.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .formatters import CodeFormatter

logger = logging.getLogger(__name__)


def setup_code_formatter(project_root: Path | None = None) -> CodeFormatter:
    """Setup automatic code formatting on task completion.

    This is an OPT-IN function. The code formatter will NOT subscribe to events
    unless this function is explicitly called.

    Args:
        project_root: Path to project root (defaults to current directory)

    Returns:
        CodeFormatter instance with event subscription registered
    """
    from . import get_bus

    if project_root is None:
        project_root = Path.cwd()

    formatter = CodeFormatter(project_root=project_root)

    bus = get_bus()
    bus.subscribe("planning.item.state.changed", formatter.handle_task_done)

    logger.info("Code formatter registered with event bus")
    return formatter
