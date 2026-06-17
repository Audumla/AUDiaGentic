"""Settings loader for the foundation event layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EventStoreSettings:
    """Event store settings."""

    enabled: bool = True
    path: str = "runtime/foundation/events"
    retention_days: int = 365


@dataclass
class EventCycleDetectionSettings:
    """Cycle detection settings."""

    max_depth: int = 10
    correlation_tracking: bool = True


@dataclass
class EventReplaySettings:
    """Replay settings."""

    dispatch_on_replay: bool = False


@dataclass
class EventLayerConfig:
    """Settings for the foundation event layer."""

    root: Path | None = None
    event_store: EventStoreSettings = field(default_factory=EventStoreSettings)
    cycle_detection: EventCycleDetectionSettings = field(default_factory=EventCycleDetectionSettings)
    replay: EventReplaySettings = field(default_factory=EventReplaySettings)


def load_event_config(root: Path | None = None) -> EventLayerConfig:
    """Load event-layer settings from `.audiagentic/event/config.yaml`."""
    if root is None:
        root = _find_event_root()

    config_path = root / ".audiagentic" / "event" / "config.yaml"

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            return EventLayerConfig(
                root=root,
                event_store=EventStoreSettings(
                    enabled=data.get("runtime", {}).get("event_store", {}).get("enabled", True),
                    path=data.get("runtime", {}).get("event_store", {}).get("path", "runtime/foundation/events"),
                    retention_days=data.get("runtime", {}).get("event_store", {}).get("retention_days", 365),
                ),
                cycle_detection=EventCycleDetectionSettings(
                    max_depth=data.get("runtime", {}).get("cycle_detection", {}).get("max_depth", 10),
                    correlation_tracking=data.get("runtime", {}).get("cycle_detection", {}).get("correlation_tracking", True),
                ),
                replay=EventReplaySettings(
                    dispatch_on_replay=data.get("runtime", {}).get("replay", {}).get("dispatch_on_replay", False),
                ),
            )
        except Exception:
            logger.warning("Failed to load config from %s, using defaults", config_path, exc_info=True)
            return EventLayerConfig(root=root)

    logger.debug("Config file not found at %s, using defaults", config_path)
    return EventLayerConfig(root=root)


def _find_event_root() -> Path:
    """Find project root by walking up from current directory."""
    import os

    if os.environ.get("AUDIAGENTIC_ROOT"):
        return Path(os.environ["AUDIAGENTIC_ROOT"]).resolve()

    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".audiagentic").exists():
            return parent

    return current
