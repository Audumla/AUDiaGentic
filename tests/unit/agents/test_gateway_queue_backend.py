from __future__ import annotations

import pytest

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


def test_queue_dead_letter_can_be_inspected_requeued_and_purged() -> None:
    now = [0.0]
    queue = InMemoryAgentWorkQueue(clock=lambda: now[0], max_delivery_attempts=1)
    consumer = ConsumerIdentity("c1", "owner-1")
    queue.publish("req-admin", attempt_epoch=1)
    claim = queue.claim(consumer, visibility_seconds=1)
    assert claim is not None
    now[0] = 2.0
    assert queue.claim(consumer, visibility_seconds=1) is None
    assert queue.inspect_dead_letter() == ("req-admin",)
    assert queue.requeue_dead_letter(("req-admin",)) == 1
    claim = queue.claim(consumer, visibility_seconds=1)
    assert claim is not None
    queue.nack(claim.claim, disposition=NackDisposition.DEAD_LETTER)
    assert queue.purge_dead_letter(("req-admin",)) == 1
    assert queue.inspect_dead_letter() == ()


def test_stale_owner_epoch_cannot_mutate_redelivered_claim() -> None:
    """A restarted consumer may reuse its id, never its former receipt."""
    now = [0.0]
    queue = InMemoryAgentWorkQueue(clock=lambda: now[0])
    first_owner = ConsumerIdentity("worker-1", "owner-before-restart")
    current_owner = ConsumerIdentity("worker-1", "owner-after-restart")
    queue.publish("req-fenced", attempt_epoch=1)
    stale = queue.claim(first_owner, visibility_seconds=1)
    assert stale is not None

    now[0] = 2.0
    current = queue.claim(current_owner, visibility_seconds=30)
    assert current is not None
    assert current.claim.owner_epoch == "owner-after-restart"

    with pytest.raises(KeyError, match="consumer epoch"):
        queue.renew(stale.claim)
    with pytest.raises(KeyError, match="consumer epoch"):
        queue.ack(stale.claim)
    with pytest.raises(KeyError, match="consumer epoch"):
        queue.nack(stale.claim, disposition=NackDisposition.DEAD_LETTER)

    assert queue.health().claimed == 1
    assert queue.dead_letter_ids() == ()
    queue.ack(current.claim)
    assert queue.health().claimed == 0


def test_expired_or_duplicate_receipt_cannot_ack_a_new_delivery() -> None:
    """Duplicate/reordered broker callbacks cannot acknowledge another lease."""
    now = [0.0]
    queue = InMemoryAgentWorkQueue(clock=lambda: now[0])
    owner = ConsumerIdentity("worker-1", "owner-1")
    queue.publish("req-duplicate", attempt_epoch=1)
    first = queue.claim(owner, visibility_seconds=1)
    assert first is not None

    now[0] = 2.0
    redelivery = queue.claim(owner, visibility_seconds=30)
    assert redelivery is not None
    assert redelivery.claim.token != first.claim.token

    with pytest.raises(KeyError, match="consumer epoch"):
        queue.ack(first.claim)
    assert queue.health().claimed == 1
    queue.ack(redelivery.claim)
    assert queue.claim(owner, visibility_seconds=30) is None
