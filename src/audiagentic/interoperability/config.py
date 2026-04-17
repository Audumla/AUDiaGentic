"""Configuration loading for the interoperability event layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EventStoreConfig:
    """Event store configuration."""

    enabled: bool = True
    path: str = "runtime/interoperability/events"
    retention_days: int = 365


@dataclass
class AsyncQueueConfig:
    """Async queue configuration."""

    enabled: bool = True
    max_queue_size: int = 10000
    shutdown_timeout: int = 30  # seconds
    persist_on_checkpoint: bool = False  # V2: persist queue to disk on crash


@dataclass
class CycleDetectionConfig:
    """Cycle detection configuration."""

    max_depth: int = 10
    correlation_tracking: bool = True


@dataclass
class ReplayConfig:
    """Replay configuration."""

    dispatch_on_replay: bool = False  # Default: skip replayed events


@dataclass
class InteroperabilityConfig:
    """Configuration for the interoperability event layer.

    Attributes:
        root: Project root directory (auto-detected if None)
        event_store: Event store configuration
        async_queue: Async queue configuration
        cycle_detection: Cycle detection configuration
        replay: Replay configuration
    """

    root: Path | None = None
    event_store: EventStoreConfig = field(default_factory=EventStoreConfig)
    async_queue: AsyncQueueConfig = field(default_factory=AsyncQueueConfig)
    cycle_detection: CycleDetectionConfig = field(default_factory=CycleDetectionConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)


def load_config(root: Path | None = None) -> InteroperabilityConfig:
    """Load interoperability configuration from file.

    Args:
        root: Project root directory (auto-detected if None)

    Returns:
        InteroperabilityConfig: Loaded configuration
    """
    if root is None:
        root = _find_root()

    config_path = root / ".audiagentic" / "interoperability" / "config.yaml"

    if config_path.exists():
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}

            return InteroperabilityConfig(
                root=root,
                event_store=EventStoreConfig(
                    enabled=data.get("runtime", {}).get("event_store", {}).get("enabled", True),
                    path=data.get("runtime", {})
                    .get("event_store", {})
                    .get("path", "runtime/interoperability/events"),
                    retention_days=data.get("runtime", {})
                    .get("event_store", {})
                    .get("retention_days", 365),
                ),
                async_queue=AsyncQueueConfig(
                    enabled=data.get("runtime", {}).get("async_queue", {}).get("enabled", True),
                    max_queue_size=data.get("runtime", {})
                    .get("async_queue", {})
                    .get("max_queue_size", 10000),
                    shutdown_timeout=data.get("runtime", {})
                    .get("async_queue", {})
                    .get("shutdown_timeout", 30),
                    persist_on_checkpoint=data.get("runtime", {})
                    .get("async_queue", {})
                    .get("persist_on_checkpoint", False),
                ),
                cycle_detection=CycleDetectionConfig(
                    max_depth=data.get("runtime", {})
                    .get("cycle_detection", {})
                    .get("max_depth", 10),
                    correlation_tracking=data.get("runtime", {})
                    .get("cycle_detection", {})
                    .get("correlation_tracking", True),
                ),
                replay=ReplayConfig(
                    dispatch_on_replay=data.get("runtime", {})
                    .get("replay", {})
                    .get("dispatch_on_replay", False),
                ),
            )
        except Exception as e:
            logger.warning("Failed to load config from %s: %s, using defaults", config_path, e)
            return InteroperabilityConfig(root=root)
    else:
        logger.debug("Config file not found at %s, using defaults", config_path)
        return InteroperabilityConfig(root=root)


def _find_root() -> Path:
    """Find project root by walking up from current directory.

    Returns:
        Path: Project root directory
    """
    import os

    # Check AUDIAGENTIC_ROOT env var first
    if os.environ.get("AUDIAGENTIC_ROOT"):
        return Path(os.environ["AUDIAGENTIC_ROOT"]).resolve()

    # Walk up from current directory looking for .audiagentic/
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".audiagentic").exists():
            return parent

    # Fallback to current directory
    return current
