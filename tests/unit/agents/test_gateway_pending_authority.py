"""AS101 deterministic pending authority tests."""

from __future__ import annotations

from audiagentic.components.agents.gateway.queue.pending import PendingAuthority


def test_pending_authority_preserves_project_fifo() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="project-a", value="first")
    pending.enqueue(request_id="a-2", project_key="project-a", value="second")

    assert pending.claim_next(lambda _: True).request_id == "a-1"  # type: ignore[union-attr]
    assert pending.claim_next(lambda _: True).request_id == "a-2"  # type: ignore[union-attr]


def test_pending_authority_rotates_projects_without_bypassing_a_blocked_head() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="project-a", value="blocked")
    pending.enqueue(request_id="a-2", project_key="project-a", value="later")
    pending.enqueue(request_id="b-1", project_key="project-b", value="ready")

    first = pending.claim_next(lambda request: request.value == "ready")
    assert first is not None and first.request_id == "b-1"
    # The later request in A cannot leapfrog its blocked FIFO head.
    assert pending.claim_next(lambda request: request.value == "later") is None
    assert pending.claim_next(lambda request: request.value in {"blocked", "later"}).request_id == "a-1"  # type: ignore[union-attr]
    assert pending.claim_next(lambda request: request.value == "later").request_id == "a-2"  # type: ignore[union-attr]


def test_pending_authority_cancellation_clears_index_and_keeps_fifo() -> None:
    pending: PendingAuthority[int] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="project-a", value=1)
    pending.enqueue(request_id="a-2", project_key="project-a", value=2)

    removed = pending.remove("a-1")
    assert removed is not None and removed.value == 1
    assert not pending.contains("a-1")
    assert pending.depths() == {"project-a": 1}
    next_request = pending.claim_next(lambda _: True)
    assert next_request is not None and next_request.request_id == "a-2"
    assert pending.depths() == {}
