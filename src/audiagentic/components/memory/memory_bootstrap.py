"""Memory component bootstrap — post-install initialization.

Called by the component loader when the memory component is installed.
Ensures runtime state directories exist and seeds default state.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap(project_root: Path) -> dict:
    """Run post-install bootstrap for the memory component.

    Creates runtime state directories and initializes default component state
    if not already present.
    """
    from audiagentic.foundation.features.state import (
        get_component_state,
        shard_dir,
    )

    # Ensure shard directory exists
    shard = shard_dir(project_root)
    shard.mkdir(parents=True, exist_ok=True)

    # Initialize empty component state if not present
    get_component_state(project_root, "memory")

    logger.info("Memory component bootstrapped", extra={"project_root": str(project_root)})
    return {"ok": True, "shard_dir": str(shard)}
