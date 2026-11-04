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


def test_a_blocked_head_in_one_lane_does_not_hold_back_another_lane_of_the_same_project() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="project", value="blocked", lane="account-a|project")
    pending.enqueue(request_id="b-1", project_key="project", value="ready", lane="account-b|project")

    claimed = pending.claim_next(lambda request: request.value == "ready")
    assert claimed is not None and claimed.request_id == "b-1"
    assert pending.count(lambda request: request.project_key == "project") == 1  # counting stays per project


def test_structured_lanes_cannot_collide_across_projects_or_profiles() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    # A string join of these two pairs would be identical ("a|b|c"); as tuples they are distinct lanes.
    pending.enqueue(request_id="x", project_key="b|c", value="x", lane=("a", "b|c"))
    pending.enqueue(request_id="y", project_key="c", value="y", lane=("a|b", "c"))

    assert pending.depths() == {"b|c": 1, "c": 1}
    assert pending.claim_next(lambda request: request.value == "y").request_id == "y"  # type: ignore[union-attr]
    assert pending.remove("x") is not None and pending.depths() == {}


def test_depths_aggregate_all_lanes_of_a_project() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="p", value="1", lane=("one", "p"))
    pending.enqueue(request_id="a-2", project_key="p", value="2", lane=("two", "p"))
    pending.enqueue(request_id="q-1", project_key="q", value="3", lane=("one", "q"))

    assert pending.depths() == {"p": 2, "q": 1}


def test_cancelling_the_last_request_of_a_lane_leaves_other_lanes_and_projects_served() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="a-1", project_key="p", value="1", lane=("one", "p"))
    pending.enqueue(request_id="a-2", project_key="p", value="2", lane=("two", "p"))
    pending.enqueue(request_id="q-1", project_key="q", value="3", lane=("one", "q"))

    assert pending.remove("a-1") is not None
    assert [head.request_id for head in pending.candidates()] == ["a-2", "q-1"]
    assert pending.remove("a-2") is not None
    assert [head.request_id for head in pending.candidates()] == ["q-1"]


def test_projects_rotate_fairly_while_blocked_and_eligible_lanes_share_a_project() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    for index in range(2):
        pending.enqueue(request_id=f"p-blocked-{index}", project_key="p", value="blocked", lane=("one", "p"))
        pending.enqueue(request_id=f"p-ready-{index}", project_key="p", value="ready", lane=("two", "p"))
        pending.enqueue(request_id=f"q-ready-{index}", project_key="q", value="ready", lane=("one", "q"))

    claimed = [pending.claim_next(lambda request: request.value == "ready").request_id for _ in range(4)]  # type: ignore[union-attr]
    # Projects alternate; the blocked lane's heads are never taken and never stop the project's other lane.
    assert claimed == ["p-ready-0", "q-ready-0", "p-ready-1", "q-ready-1"]
    assert pending.depths() == {"p": 2}


def test_a_replenished_lane_cannot_overtake_an_older_eligible_head_of_another_lane() -> None:
    pending: PendingAuthority[str] = PendingAuthority()
    pending.enqueue(request_id="old", project_key="p", value="x", lane=("one", "p"))
    pending.enqueue(request_id="busy-1", project_key="p", value="x", lane=("two", "p"))
    order = []
    for index in range(3):
        order.append(pending.claim_next(lambda _: True).request_id)  # type: ignore[union-attr]
        pending.enqueue(request_id=f"busy-{index + 2}", project_key="p", value="x", lane=("two", "p"))
    assert order[0] == "old" and order[1] == "busy-1" and order[2] == "busy-2"  # strictly oldest-head first
