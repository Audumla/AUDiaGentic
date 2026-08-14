"""AS101 deterministic tests for the source-capacity authority seam."""

from __future__ import annotations

from audiagentic.components.agents.gateway.queue.capacity import (
    ScopedCapacityAuthority,
    SourceCapacityAuthority,
)


def test_capacity_authority_fences_shared_source_and_releases_idempotently() -> None:
    authority = SourceCapacityAuthority()
    first = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=1, model_id="model-a",
    )
    assert first is not None
    assert authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=1, model_id="model-a",
    ) is None

    authority.release(first)
    authority.release(first)
    second = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=1, model_id="model-a",
    )
    assert second is not None


def test_capacity_authority_uses_injected_clock_for_drain_before_swap() -> None:
    now = [0.0]
    authority = SourceCapacityAuthority(clock=lambda: now[0], starvation_seconds=10.0)
    active = authority.try_reserve(
        source_id="source-a", resource_id="swap-host", concurrency=2, model_id="model-a",
    )
    assert active is not None
    # A different model shares the host and must wait for a drain.
    assert authority.try_reserve(
        source_id="source-b", resource_id="swap-host", concurrency=2, model_id="model-b",
    ) is None

    now[0] = 11.0
    # Once another source has waited past the policy threshold, new work for
    # the active source is refused so its in-flight work can drain.
    assert authority.try_reserve(
        source_id="source-a", resource_id="swap-host", concurrency=2, model_id="model-a",
    ) is None
    authority.release(active)

    swapped = authority.try_reserve(
        source_id="source-b", resource_id="swap-host", concurrency=2, model_id="model-b",
    )
    assert swapped is not None
    assert authority.snapshot("swap-host")["active-source-id"] == "source-b"


def test_physical_release_is_token_idempotent_while_another_lease_is_live() -> None:
    authority = SourceCapacityAuthority()
    first = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=2, model_id="model-a",
    )
    second = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=2, model_id="model-a",
    )
    assert first is not None and second is not None

    authority.release(first)
    authority.release(first)
    assert authority.snapshot("gpu-0")["in-flight"] == {"source-a": 1}
    third = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=2, model_id="model-a",
    )
    assert third is not None


def test_overlay_release_is_token_idempotent_while_another_lease_is_live() -> None:
    authority = ScopedCapacityAuthority()
    first = authority.try_reserve((("global", 2),))
    second = authority.try_reserve((("global", 2),))
    assert first is not None and second is not None

    authority.release(first)
    authority.release(first)
    assert authority.snapshot() == {"global": 1}
    third = authority.try_reserve((("global", 2),))
    assert third is not None


def test_capacity_status_is_provider_neutral_and_not_lane_policy() -> None:
    authority = SourceCapacityAuthority()
    reservation = authority.try_reserve(
        source_id="source-a", resource_id="gpu-0", concurrency=2, model_id="model-a",
    )
    assert reservation is not None
    status = authority.snapshots()
    assert status["gpu-0"]["active-source-id"] == "source-a"
    assert status["gpu-0"]["in-flight"] == {"source-a": 1}
    assert "lane" not in status["gpu-0"]
    assert "virtual-capacity" not in status["gpu-0"]
