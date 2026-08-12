from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.queue.backend import (
    ConsumerIdentity,
    InMemoryAgentWorkQueue,
)
from audiagentic.components.agents.gateway.queue.outbox import DurablePublicationOutbox


def test_outbox_replays_publish_after_crash_before_mark(tmp_path: Path) -> None:
    outbox = DurablePublicationOutbox()
    queue = InMemoryAgentWorkQueue()
    outbox.stage(tmp_path, "req-1", attempt_epoch=1)

    def crash_after_publish(_intent, _receipt):
        raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        outbox.flush(tmp_path, queue, after_publish=crash_after_publish)

    receipts = outbox.flush(tmp_path, queue)
    assert len(receipts) == 1
    claim = queue.claim(ConsumerIdentity("worker-a", "epoch-1"), visibility_seconds=30)
    assert claim is not None
    assert claim.request_id == "req-1"


def test_outbox_stage_is_attempt_idempotent(tmp_path: Path) -> None:
    outbox = DurablePublicationOutbox()
    first = outbox.stage(tmp_path, "req-2", attempt_epoch=3)
    second = outbox.stage(tmp_path, "req-2", attempt_epoch=3)
    assert second == first
