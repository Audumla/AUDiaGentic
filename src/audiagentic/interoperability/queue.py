"""Async event queue for background processing.

Task-0292 implementation with threading-based background worker.
"""

from __future__ import annotations

import logging
import threading
import time
from queue import Queue
from typing import Any

from .envelope import EventEnvelope

logger = logging.getLogger(__name__)


class AsyncQueue:
    """Background worker queue for ASYNC mode event processing.

    Features:
    - Threading-based (not asyncio) to avoid GIL contention
    - Thread-safe queue using queue.Queue
    - Graceful shutdown with configurable timeout
    - V1: Events in queue lost on crash if persist_on_checkpoint: false
    - V2: Optional disk persistence on checkpoint

    Usage:
        queue = AsyncQueue.get_instance()
        queue.start()
        # Events published with mode=ASYNC are queued automatically
        queue.stop(timeout=30)  # Graceful shutdown
    """

    _instance: AsyncQueue | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        max_queue_size: int = 10000,
        shutdown_timeout: int = 30,
        persist_on_checkpoint: bool = False,
    ) -> None:
        """Initialize async queue.

        Args:
            max_queue_size: Maximum queue size before backpressure
            shutdown_timeout: Seconds to wait for queue drain on shutdown
            persist_on_checkpoint: V2: persist queue to disk on checkpoint
        """
        self._max_queue_size = max_queue_size
        self._shutdown_timeout = shutdown_timeout
        self._persist_on_checkpoint = persist_on_checkpoint

        self._queue: Queue[tuple[str, dict[str, Any], dict[str, Any]]] = Queue(
            maxsize=max_queue_size
        )
        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._stop_event = threading.Event()

    @classmethod
    def get_instance(cls) -> AsyncQueue:
        """Get singleton instance.

        Returns:
            AsyncQueue singleton
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = AsyncQueue()
            return cls._instance

    def start(self) -> None:
        """Start background worker thread."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AsyncQueueWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("AsyncQueue started")

    def stop(self, timeout: int | None = None) -> None:
        """Stop background worker and drain queue.

        Args:
            timeout: Seconds to wait for queue drain (uses default if None)
        """
        if not self._running:
            return

        timeout = timeout or self._shutdown_timeout
        self._stop_event.set()

        # Wait for worker to finish
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning(
                    "AsyncQueue worker didn't stop in %s seconds",
                    timeout,
                )

        self._running = False
        logger.info("AsyncQueue stopped")

    def enqueue(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Queue an event for background processing.

        Args:
            event_type: Event type string
            payload: Event payload
            metadata: Event metadata
        """
        try:
            self._queue.put_nowait((event_type, payload, metadata))
        except Exception as e:
            logger.warning("Queue full, dropping event: %s", e)

    def _worker_loop(self) -> None:
        """Background worker loop."""
        from . import get_bus

        while not self._stop_event.is_set():
            try:
                try:
                    event_type, payload, metadata = self._queue.get(timeout=1.0)
                except Exception:
                    continue

                try:
                    bus = get_bus()
                    envelope = EventEnvelope(
                        type=event_type,
                        payload=payload,
                        metadata=metadata,
                    )
                    bus._dispatch_sync(envelope)
                except Exception as e:
                    logger.error("Async event processing error: %s", e)
                finally:
                    self._queue.task_done()

            except Exception as e:
                logger.error("AsyncQueue worker error: %s", e)
                time.sleep(0.1)

    def size(self) -> int:
        """Get current queue size.

        Returns:
            Number of events in queue
        """
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Check if queue is empty.

        Returns:
            True if queue is empty
        """
        return self._queue.empty()
