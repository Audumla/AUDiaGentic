"""Durable file-spool event transport for cross-process trigger ingress (SH09).

The smallest transport that meets the evidenced requirements of the one
current cross-process gateway trigger (durable once-only admission despite
redelivery, offline publishing while the consumer is down, single-machine
deployment, poison isolation): an append-only spool of atomic JSON event
files consumed in order and acknowledged by atomic file moves. No broker,
daemon, or network dependency — a broker remains an option behind the same
seam if a future trigger evidences requirements this cannot meet.

Layout under one spool root::

    pending/<event-id>.json      durably published, awaiting delivery
    dead-letter/<event-id>.json  poison or delivery-exhausted events

Guarantees:
- ``publish`` is atomic and durable: the event file appears in ``pending``
  complete or not at all (unique name + atomic replace).
- ``consume`` delivers pending events oldest-first. A successful handler
  acknowledges by deleting the file. ``SpoolPoison`` dead-letters the event
  immediately; any other handler exception leaves the event for redelivery
  with a persisted attempt count, dead-lettering after ``max_attempts``.
- Consumers must be idempotent: a crash between handler success and the
  acknowledging delete redelivers the event. The event's ``event-id`` is the
  stable delivery identity consumers map to their own idempotency contract.
- One consumer process at a time (the owning service); publishing is safe
  from any number of processes concurrently.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z

spool_validation_error = make_error_factory("VAL", "SPOOL", "event-spool")
spool_io_error = make_error_factory("IO", "SPOOL", "event-spool")

DEFAULT_MAX_DELIVERY_ATTEMPTS = 5
_PENDING = "pending"
_DEAD_LETTER = "dead-letter"


class SpoolPoison(Exception):
    """Raised by a consumer handler to dead-letter the event immediately."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _new_event_id() -> str:
    """Time-ordered unique id; lexicographic order == publish order."""
    return f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"


class DurableSpoolTransport:
    """One spool root's publish/consume/dead-letter surface."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_topics: Iterable[str],
        max_delivery_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
    ) -> None:
        self.root = root
        self._allowed_topics = frozenset(allowed_topics)
        if not self._allowed_topics:
            raise spool_validation_error(1, "spool requires at least one allowed topic")
        if max_delivery_attempts < 1:
            raise spool_validation_error(2, "max delivery attempts must be >= 1")
        self._max_attempts = max_delivery_attempts

    @property
    def pending_dir(self) -> Path:
        return self.root / _PENDING

    @property
    def dead_letter_dir(self) -> Path:
        return self.root / _DEAD_LETTER

    # ── publish side (any process) ───────────────────────────────

    def publish(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Durably spool one event; returns its event-id (delivery identity)."""
        if topic not in self._allowed_topics:
            raise spool_validation_error(
                3, "topic is not accepted by this spool", topic=topic,
                allowed=sorted(self._allowed_topics),
            )
        if not isinstance(payload, Mapping):
            raise spool_validation_error(4, "spool event payload must be a mapping")
        event_id = _new_event_id()
        record = {
            "event-id": event_id,
            "topic": topic,
            "payload": dict(payload),
            "metadata": dict(metadata or {}),
            "published-at": now_iso_z(),
            "attempts": 0,
        }
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.pending_dir / f"{event_id}.json", record)
        return event_id

    # ── consume side (owning service only) ───────────────────────

    def pending_count(self) -> int:
        try:
            return sum(1 for _ in self.pending_dir.glob("*.json"))
        except OSError:
            return 0

    def dead_letter_ids(self) -> list[str]:
        try:
            return sorted(path.stem for path in self.dead_letter_dir.glob("*.json"))
        except OSError:
            return []

    def consume(
        self,
        handler: Callable[[dict[str, Any]], None],
        *,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Deliver pending events oldest-first; returns outcome counters.

        ``handler`` receives the full event record (event-id/topic/payload/
        metadata). Success acknowledges (deletes) the event. ``SpoolPoison``
        dead-letters it. Any other exception persists an incremented attempt
        count and stops the sweep (ordering is part of the contract — a
        transiently failing head must not be overtaken), dead-lettering once
        attempts are exhausted.
        """
        delivered = failed = poisoned = 0
        for path in sorted(self.pending_dir.glob("*.json")):
            if limit is not None and delivered + failed + poisoned >= limit:
                break
            record = self._read_event(path)
            if record is None:
                self._move_to_dead_letter(path)
                poisoned += 1
                continue
            try:
                handler(record)
            except SpoolPoison:
                self._move_to_dead_letter(path)
                poisoned += 1
                continue
            except Exception:  # noqa: BLE001 — classified transient; bounded retries
                record["attempts"] = int(record.get("attempts", 0)) + 1
                if record["attempts"] >= self._max_attempts:
                    atomic_write_json(path, record)
                    self._move_to_dead_letter(path)
                    poisoned += 1
                    continue
                atomic_write_json(path, record)
                failed += 1
                break
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # redelivery is safe: consumers are idempotent by contract
            delivered += 1
        return {"delivered": delivered, "failed": failed, "dead-lettered": poisoned}

    def replay_dead_letter(self, event_id: str) -> None:
        """Move one dead-lettered event back to pending with a reset budget."""
        source = self.dead_letter_dir / f"{event_id}.json"
        record = self._read_event(source)
        if record is None:
            raise spool_validation_error(5, "dead-letter event not found or unreadable", event_id=event_id)
        record["attempts"] = 0
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.pending_dir / f"{event_id}.json", record)
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_event(self, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or not value.get("event-id") or not value.get("topic"):
            return None
        return value

    def _move_to_dead_letter(self, path: Path) -> None:
        self.dead_letter_dir.mkdir(parents=True, exist_ok=True)
        target = self.dead_letter_dir / path.name
        try:
            os.replace(path, target)
        except OSError:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["DurableSpoolTransport", "SpoolPoison", "DEFAULT_MAX_DELIVERY_ATTEMPTS"]
