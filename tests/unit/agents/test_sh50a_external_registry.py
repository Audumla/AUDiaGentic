"""SH50a: external session registry with a single generation-fenced writer claim."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import gateway_external_sessions_root
from audiagentic.components.agents.gateway.session import external_registry as registry
from audiagentic.foundation.contracts.errors import AudiaGenticError

KEY = "a" * 64
BASIS = {"evidence-id": "qe_" + "a" * 24, "executable-digest": "sha256:" + "a" * 64,
         "executable-version": "0.165.0", "instance-generation": "g1"}


def _register(root: Path, **changes):
    values = dict(ref_key=KEY, provider_id="codex", surface_id="codex-app-server", node_locator="loc-1", basis=BASIS)
    values.update(changes)
    return registry.register(root, **values)


def _code(call) -> str:
    with pytest.raises(AudiaGenticError) as raised:
        call()
    return raised.value.code


def test_register_is_idempotent_and_supersedes_on_change(tmp_path: Path) -> None:
    first = _register(tmp_path)
    assert (first["generation"], first["writer"]) == (1, None)
    assert _register(tmp_path) == first  # unchanged: same record, not rewritten
    moved = _register(tmp_path, node_locator="loc-2")
    assert moved["generation"] == 2 and moved["created-at"] == first["created-at"]
    rebased = _register(tmp_path, basis={**BASIS, "instance-generation": "g2"})
    assert rebased["generation"] == 3
    assert registry.get_registration(tmp_path, KEY) == rebased


def test_one_writer_at_a_time(tmp_path: Path) -> None:
    _register(tmp_path)
    claimed = registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    assert claimed["writer"]["writer-id"] == "gw-a" and claimed["writer"]["owner-epoch"] == "e1"
    assert registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1) == claimed  # same writer: no-op
    assert _code(lambda: registry.claim_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=1)) == "CON-XSR-008"
    registry.assert_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    assert _code(lambda: registry.assert_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=1)) == "CON-XSR-010"


def test_stale_generation_cannot_claim_or_write(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    superseded = _register(tmp_path, node_locator="loc-2")
    assert superseded["writer"] is None  # the old holder lost the claim with the old generation
    assert _code(lambda: registry.assert_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)) == "CON-XSR-007"
    assert _code(lambda: registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)) == "CON-XSR-007"
    registry.claim_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=2)


def test_release_is_holder_only(tmp_path: Path) -> None:
    _register(tmp_path)
    assert registry.release_writer(tmp_path, KEY, writer_id="gw-a", generation=1)["writer"] is None  # nothing held
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    assert _code(lambda: registry.release_writer(tmp_path, KEY, writer_id="gw-b", generation=1)) == "CON-XSR-009"
    assert registry.release_writer(tmp_path, KEY, writer_id="gw-a", generation=1)["writer"] is None
    registry.claim_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=1)


def test_concurrent_claims_have_exactly_one_winner(tmp_path: Path) -> None:
    _register(tmp_path)
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def attempt(index: int) -> None:
        barrier.wait()
        try:
            registry.claim_writer(tmp_path, KEY, writer_id=f"gw-{index}", owner_epoch="e1", generation=1)
            outcomes.append("won")
        except AudiaGenticError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert outcomes.count("won") == 1 and outcomes.count("CON-XSR-008") == 7


def test_claim_survives_restart_and_corruption_fails_closed(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    # A new process sees the same durable claim (no in-memory state).
    assert registry.get_registration(tmp_path, KEY)["writer"]["writer-id"] == "gw-a"
    path = gateway_external_sessions_root(tmp_path) / f"{KEY}.json"
    path.write_text("{not json", encoding="utf-8")
    assert _code(lambda: registry.get_registration(tmp_path, KEY)) == "VAL-XSR-002"
    assert _code(lambda: registry.claim_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=1)) == "VAL-XSR-002"
    path.write_text(json.dumps({**json.loads(json.dumps(_register_dict())), "ref-key": "b" * 64}), encoding="utf-8")
    assert _code(lambda: registry.get_registration(tmp_path, KEY)) == "VAL-XSR-003"


def _register_dict() -> dict:
    return {"schema-version": 1, "ref-key": KEY, "provider-id": "codex", "surface-id": "codex-app-server",
            "node-locator": "loc-1", "generation": 1, "basis": BASIS, "writer": None,
            "created-at": "2026-10-29T00:00:00Z", "updated-at": "2026-10-29T00:00:00Z"}


def test_inputs_are_validated(tmp_path: Path) -> None:
    assert _code(lambda: _register(tmp_path, ref_key="../escape")) == "VAL-XSR-004"
    assert _code(lambda: _register(tmp_path, basis={"evidence-id": BASIS["evidence-id"]})) == "VAL-XSR-005"
    assert _code(lambda: _register(tmp_path, basis={**BASIS, "evidence-id": "bad"})) == "VAL-XSR-001"
    assert _code(lambda: registry.claim_writer(tmp_path, "c" * 64, writer_id="gw", owner_epoch="e1", generation=1)) == "VAL-XSR-011"
    _register(tmp_path)
    assert _code(lambda: _register(tmp_path, provider_id="pi")) == "CON-XSR-006"
    assert registry.get_registration(tmp_path, "d" * 64) is None


# ── SH50b: owner-epoch fencing and canonical target resolution ──────────────


def test_claim_from_a_retired_owner_epoch_is_taken_over_and_fenced(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e1", generation=1)
    # The gateway restarted: a new owner epoch takes over; the same writer id does not matter.
    taken = registry.claim_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e2", generation=1)
    assert taken["generation"] == 2 and taken["writer"]["owner-epoch"] == "e2"
    # The retired owner can no longer act, whether it knows the old or the new generation.
    assert _code(lambda: registry.assert_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e1", generation=1)) \
        == "CON-XSR-007"
    assert _code(lambda: registry.assert_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e1", generation=2)) \
        == "CON-XSR-012"
    assert _code(lambda: registry.claim_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e1", generation=1)) \
        == "CON-XSR-007"
    registry.assert_writer(tmp_path, KEY, writer_id="gw", owner_epoch="e2", generation=2)


def test_same_epoch_still_allows_only_one_writer(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    assert _code(lambda: registry.claim_writer(tmp_path, KEY, writer_id="gw-b", owner_epoch="e1", generation=1)) \
        == "CON-XSR-008"
    assert registry.get_registration(tmp_path, KEY)["generation"] == 1  # refusal changed nothing


def test_target_is_resolved_only_for_the_asserted_writer(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    target = registry.resolve_target(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    assert (target.provider_id, target.surface_id, target.node_locator, target.generation) == (
        "codex", "codex-app-server", "loc-1", 1)
    assert (target.evidence_id, target.instance_generation) == (BASIS["evidence-id"], "g1")
    for kwargs, code in (({"writer_id": "gw-b", "owner_epoch": "e1", "generation": 1}, "CON-XSR-010"),
                         ({"writer_id": "gw-a", "owner_epoch": "e2", "generation": 1}, "CON-XSR-012"),
                         ({"writer_id": "gw-a", "owner_epoch": "e1", "generation": 2}, "CON-XSR-007")):
        assert _code(lambda kwargs=kwargs: registry.resolve_target(tmp_path, KEY, **kwargs)) == code


def test_superseded_registration_cannot_resolve_an_old_locator(tmp_path: Path) -> None:
    _register(tmp_path)
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)
    _register(tmp_path, node_locator="loc-2")
    assert _code(lambda: registry.resolve_target(
        tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=1)) == "CON-XSR-007"
    registry.claim_writer(tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=2)
    assert registry.resolve_target(
        tmp_path, KEY, writer_id="gw-a", owner_epoch="e1", generation=2).node_locator == "loc-2"
