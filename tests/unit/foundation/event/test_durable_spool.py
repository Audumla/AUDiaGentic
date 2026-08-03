"""SH09 — DurableSpoolTransport publish/consume/dead-letter contract."""
from __future__ import annotations

import json

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event.durable_spool import DurableSpoolTransport, SpoolPoison

TOPIC = "agents.execution.gateway.requested"


def _spool(tmp_path, **kwargs) -> DurableSpoolTransport:
    return DurableSpoolTransport(tmp_path / "spool", allowed_topics={TOPIC}, **kwargs)


def test_publish_and_ordered_consume(tmp_path):
    spool = _spool(tmp_path)
    first = spool.publish(TOPIC, {"n": 1}, metadata={"correlation_id": "c1"})
    second = spool.publish(TOPIC, {"n": 2})
    assert spool.pending_count() == 2

    seen: list[dict] = []
    outcome = spool.consume(seen.append)
    assert outcome == {"delivered": 2, "failed": 0, "dead-lettered": 0}
    assert [e["payload"]["n"] for e in seen] == [1, 2]
    assert seen[0]["event-id"] == first and seen[1]["event-id"] == second
    assert seen[0]["metadata"] == {"correlation_id": "c1"}
    assert spool.pending_count() == 0  # acknowledged


def test_unknown_topic_rejected(tmp_path):
    with pytest.raises(AudiaGenticError, match="VAL-SPOOL-003"):
        _spool(tmp_path).publish("agents.other", {})


def test_poison_moves_to_dead_letter_and_does_not_block(tmp_path):
    spool = _spool(tmp_path)
    bad = spool.publish(TOPIC, {"bad": True})
    spool.publish(TOPIC, {"bad": False})

    def handler(event):
        if event["payload"]["bad"]:
            raise SpoolPoison("no good")

    outcome = spool.consume(handler)
    assert outcome == {"delivered": 1, "failed": 0, "dead-lettered": 1}
    assert spool.dead_letter_ids() == [bad]
    assert spool.pending_count() == 0


def test_transient_failure_preserves_order_and_retries_bounded(tmp_path):
    spool = _spool(tmp_path, max_delivery_attempts=3)
    head = spool.publish(TOPIC, {"n": 1})
    spool.publish(TOPIC, {"n": 2})

    def failing(event):
        raise RuntimeError("transient")

    # A transiently failing head stops the sweep — ordering is contractual.
    for expected_attempts in (1, 2):
        outcome = spool.consume(failing)
        assert outcome["failed"] == 1 and outcome["delivered"] == 0
        record = json.loads((spool.pending_dir / f"{head}.json").read_text(encoding="utf-8"))
        assert record["attempts"] == expected_attempts
        assert spool.pending_count() == 2

    # Third failure exhausts the budget: head dead-letters, tail delivers.
    seen: list[dict] = []

    def fail_head(event):
        if event["event-id"] == head:
            raise RuntimeError("transient")
        seen.append(event)

    outcome = spool.consume(fail_head)
    assert outcome == {"delivered": 1, "failed": 0, "dead-lettered": 1}
    assert spool.dead_letter_ids() == [head]
    assert [e["payload"]["n"] for e in seen] == [2]


def test_replay_dead_letter_resets_budget(tmp_path):
    spool = _spool(tmp_path)
    event_id = spool.publish(TOPIC, {"n": 1})
    spool.consume(lambda e: (_ for _ in ()).throw(SpoolPoison("later")))
    assert spool.dead_letter_ids() == [event_id]

    spool.replay_dead_letter(event_id)
    assert spool.pending_count() == 1 and spool.dead_letter_ids() == []
    seen: list[dict] = []
    assert spool.consume(seen.append)["delivered"] == 1
    assert seen[0]["attempts"] == 0


def test_corrupt_event_file_dead_letters(tmp_path):
    spool = _spool(tmp_path)
    spool.pending_dir.mkdir(parents=True, exist_ok=True)
    (spool.pending_dir / "00-corrupt.json").write_text("{not json", encoding="utf-8")
    outcome = spool.consume(lambda e: None)
    assert outcome["dead-lettered"] == 1
    assert spool.pending_count() == 0


def test_redelivery_after_missed_ack_is_possible(tmp_path):
    """Crash between handler success and ack → the event is delivered again;
    consumers map event-id to their idempotency contract."""
    spool = _spool(tmp_path)
    event_id = spool.publish(TOPIC, {"n": 1})
    delivered: list[str] = []

    def handler(event):
        delivered.append(event["event-id"])

    spool.consume(handler)
    # Simulate the missed ack: restore the event file as it was.
    spool.pending_dir.mkdir(parents=True, exist_ok=True)
    (spool.pending_dir / f"{event_id}.json").write_text(
        json.dumps({"event-id": event_id, "topic": TOPIC, "payload": {"n": 1}, "metadata": {}, "attempts": 0}),
        encoding="utf-8",
    )
    spool.consume(handler)
    assert delivered == [event_id, event_id]
