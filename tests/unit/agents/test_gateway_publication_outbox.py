"""SH25 admission/publication crash-boundary conformance tests."""

from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway.queue.backend import InMemoryAgentWorkQueue
from audiagentic.components.agents.gateway.queue.outbox import DurablePublicationOutbox


def test_outbox_stages_before_publish_and_flushes_stable_identity(tmp_path):
    outbox = DurablePublicationOutbox()
    queue = InMemoryAgentWorkQueue()
    intent = outbox.stage(tmp_path, "req-1", attempt_epoch=1)
    assert intent.state == "pending"
    assert outbox.flush(tmp_path, queue)[0].request_id == "req-1"
    assert outbox.flush(tmp_path, queue) == ()
    assert queue.health().pending == 1


def test_crash_after_broker_acceptance_replays_idempotently(tmp_path):
    outbox = DurablePublicationOutbox()
    queue = InMemoryAgentWorkQueue()
    outbox.stage(tmp_path, "req-crash", attempt_epoch=2)

    def crash_after_publish(_intent, _receipt):
        raise RuntimeError("simulated crash before outbox mark")

    with pytest.raises(RuntimeError, match="simulated crash"):
        outbox.flush(tmp_path, queue, after_publish=crash_after_publish)

    # Replay uses the same request/attempt identity; the conformance fake's
    # stable publish identity makes it one pending delivery, not a loss or a
    # second logical request.
    replayed = outbox.flush(tmp_path, queue)
    assert replayed[0].request_id == "req-crash"
    assert queue.health().pending == 1
    assert outbox.flush(tmp_path, queue) == ()
