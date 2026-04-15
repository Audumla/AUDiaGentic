"""Event store interface for optional persistence.

Task-0277 implementation with atomic writes and best-effort persistence.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .envelope import EventEnvelope

logger = logging.getLogger(__name__)


class FileEventStore:
    """File-based event store with atomic writes.

    Features:
    - Atomic writes using temp file + rename pattern
    - Best-effort persistence (failures logged, don't block publish)
    - Configurable enable/disable
    - Timestamp-based filenames for chronological ordering

    Filename format: {timestamp_utc}_{sanitized_type}_{event_id}.json
    """

    def __init__(
        self,
        root: Path,
        enabled: bool = True,
        path: str = "runtime/interoperability/events",
        retention_days: int = 365,
    ) -> None:
        """Initialize file event store.

        Args:
            root: Project root directory
            enabled: Whether persistence is enabled
            path: Relative path for event files
            retention_days: Days to retain events
        """
        self._root = root
        self._enabled = enabled
        self._path = root / path
        self._retention_days = retention_days

        # Create directory if not exists
        if self._enabled:
            self._path.mkdir(parents=True, exist_ok=True)

    def persist(self, envelope: EventEnvelope) -> None:
        """Persist an event envelope to disk.

        Uses atomic writes (temp file + rename) to prevent corruption.
        Failures are logged but don't block the publish call.

        Args:
            envelope: Event envelope to persist
        """
        if not self._enabled:
            return

        try:
            # Sanitize event type for filename
            sanitized_type = re.sub(r"[^a-zA-Z0-9_]", "_", envelope.type)

            # Filename: timestamp_type_eventid.json
            timestamp = envelope.occurred_at.replace(":", "-").split(".")[0]
            filename = f"{timestamp}_{sanitized_type}_{envelope.id}.json"
            filepath = self._path / filename

            # Atomic write: temp file + rename
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self._path,
                suffix=".json",
                delete=False,
            ) as tmp:
                json.dump(envelope.to_dict(), tmp, indent=2)
                tmp_path = Path(tmp.name)

            # Rename to final name (atomic on most filesystems)
            tmp_path.rename(filepath)

        except Exception as e:
            logger.warning(
                "Persistence error for event %s: %s",
                envelope.id,
                e,
            )

    def query(
        self,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        event_type_pattern: str | None = None,
    ) -> list[EventEnvelope]:
        """Query persisted events.

        Args:
            from_timestamp: Start timestamp (inclusive), ISO 8601
            to_timestamp: End timestamp (inclusive), ISO 8601
            event_type_pattern: Event type pattern to filter

        Returns:
            List of matching event envelopes
        """
        if not self._enabled or not self._path.exists():
            return []

        events = []

        for filepath in self._path.glob("*.json"):
            try:
                with open(filepath) as f:
                    data = json.load(f)

                envelope = EventEnvelope.from_dict(data)

                # Filter by timestamp range
                if from_timestamp and envelope.occurred_at < from_timestamp:
                    continue
                if to_timestamp and envelope.occurred_at > to_timestamp:
                    continue

                # Filter by event type pattern
                if event_type_pattern:
                    if not self._pattern_matches(event_type_pattern, envelope.type):
                        continue

                events.append(envelope)

            except Exception as e:
                logger.warning("Failed to parse event file %s: %s", filepath, e)

        # Sort by timestamp
        events.sort(key=lambda e: e.occurred_at)

        return events

    def _pattern_matches(self, pattern: str, event_type: str) -> bool:
        """Check if event type matches pattern with wildcard support."""
        parts = pattern.split(".")
        event_parts = event_type.split(".")

        if "**" in parts:
            wildcard_idx = parts.index("**")
            prefix = parts[:wildcard_idx]
            suffix = parts[wildcard_idx + 1 :]

            if len(event_parts) < len(prefix) + len(suffix):
                return False

            if event_parts[: len(prefix)] != prefix:
                return False

            if suffix and event_parts[-len(suffix) :] != suffix:
                return False

            return True
        else:
            if len(parts) != len(event_parts):
                return False

            for p, e in zip(parts, event_parts):
                if p != "*" and p != e:
                    return False

            return True

    def cleanup(self, older_than_days: int | None = None) -> int:
        """Remove old event files.

        Args:
            older_than_days: Days threshold (uses config retention_days if None)

        Returns:
            Number of files removed
        """
        if not self._enabled:
            return 0

        threshold = older_than_days or self._retention_days
        cutoff = datetime.now(timezone.utc).timestamp() - (threshold * 86400)

        removed = 0
        for filepath in self._path.glob("*.json"):
            try:
                if filepath.stat().st_mtime < cutoff:
                    filepath.unlink()
                    removed += 1
            except Exception as e:
                logger.warning("Failed to remove old event file %s: %s", filepath, e)

        return removed
