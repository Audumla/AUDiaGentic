"""Settings loader for the foundation event layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

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
    max_correlation_chains: int = 4096
    max_events_per_correlation: int = 1024

    def __post_init__(self) -> None:
        for field_name in ("max_depth", "max_correlation_chains", "max_events_per_correlation"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if not isinstance(self.correlation_tracking, bool):
            raise ValueError("correlation_tracking must be a boolean")


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
    """Load event-layer settings from the ``events`` section of the resolved settings."""
    if root is None:
        root = _find_event_root()

    try:
        from audiagentic.foundation.config.settings import resolve_settings_cached

        data = resolve_settings_cached(root).get("events") or {}
        store = data.get("event_store") or {}
        cycle = data.get("cycle_detection") or {}
        replay = data.get("replay") or {}
        defaults = EventLayerConfig()
        return EventLayerConfig(
            root=root,
            event_store=EventStoreSettings(
                enabled=store.get("enabled", defaults.event_store.enabled),
                path=store.get("path", defaults.event_store.path),
                retention_days=store.get("retention_days", defaults.event_store.retention_days),
            ),
            cycle_detection=EventCycleDetectionSettings(
                max_depth=cycle.get("max_depth", defaults.cycle_detection.max_depth),
                correlation_tracking=cycle.get("correlation_tracking", defaults.cycle_detection.correlation_tracking),
                max_correlation_chains=cycle.get("max_correlation_chains", defaults.cycle_detection.max_correlation_chains),
                max_events_per_correlation=cycle.get(
                    "max_events_per_correlation", defaults.cycle_detection.max_events_per_correlation,
                ),
            ),
            replay=EventReplaySettings(
                dispatch_on_replay=replay.get("dispatch_on_replay", defaults.replay.dispatch_on_replay),
            ),
        )
    except Exception:
        logger.warning("Failed to load event settings for %s, using defaults", root, exc_info=True)
        return EventLayerConfig(root=root)


def _find_event_root() -> Path:
    """The project being operated on (AUDIAGENTIC_REPO_ROOT, else the nearest ``.audiagentic``), else cwd."""
    from audiagentic.foundation.paths.project import find_project_root

    return find_project_root() or Path.cwd()
