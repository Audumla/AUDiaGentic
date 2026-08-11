from __future__ import annotations

from audiagentic.components.agents.gateway.queue.backend import (
    ConsumerIdentity,
    InMemoryAgentWorkQueue,
    NackDisposition,
)


def test_queue_duplicate_publish_and_ack_are_idempotent() -> None:
    queue = InMemoryAgentWorkQueue()
    consumer = ConsumerIdentity("c1", "owner-1")
    assert queue.publish("req-1", attempt_epoch=1).accepted
    assert queue.publish("req-1", attempt_epoch=1).accepted
    work = queue.claim(consumer, visibility_seconds=30)
    assert work is not None
    assert queue.claim(consumer, visibility_seconds=30) is None
    queue.ack(work.claim)
    assert queue.health().claimed == 0


def test_queue_expired_visibility_redelivers_and_poison_reaches_dlq() -> None:
    now = [0.0]
    queue = InMemoryAgentWorkQueue(clock=lambda: now[0], max_delivery_attempts=2)
    consumer = ConsumerIdentity("c1", "owner-1")
    queue.publish("req-2", attempt_epoch=1)
    first = queue.claim(consumer, visibility_seconds=1)
    assert first is not None
    now[0] = 2.0
    second = queue.claim(consumer, visibility_seconds=1)
    assert second is not None
    queue.nack(second.claim, disposition=NackDisposition.DEAD_LETTER)
    assert "req-2" in queue.dead_letter_ids()


def test_queue_drain_blocks_new_publish_but_allows_existing_claim() -> None:
    queue = InMemoryAgentWorkQueue()
    consumer = ConsumerIdentity("c1", "owner-1")
    queue.publish("req-3", attempt_epoch=1)
    claimed = queue.claim(consumer, visibility_seconds=30)
    assert claimed is not None
    queue.set_draining(True)
    assert not queue.publish("req-4", attempt_epoch=1).accepted
    queue.ack(claimed.claim)
    assert queue.health().claimed == 0
