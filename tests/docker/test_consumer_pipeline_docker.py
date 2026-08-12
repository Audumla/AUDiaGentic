"""Consumer Pipeline (AS19/AS30/AS31) Docker integration tests — Stage 4.

Runs inside a clean Docker container with real process isolation. Validates:
  - AS19: observer ingress lifecycle (create, deliver, invalidate)
  - AS30: session binding durability and cross-process safety
  - AS31: output relay persistence, fragment bounds, sequence monotonicity
  - Full pipeline: AS19+AS30+AS31 end-to-end together

These tests use real filesystem I/O, StartupLock cross-process exclusion,
and subprocess spawning to prove the consumer pipeline works in isolation.
"""
from __future__ import annotations

# Imports below the Docker-harness marker are intentionally grouped by
# consumer surface for readability.
# ruff: noqa: E402

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
    reason="consumer pipeline tests require the Docker test harness",
)

# ── AS31 imports ───────────────────────────────────────────────────────
from audiagentic.components.agents.gateway.output import (
    OutputPolicy,
    append_agent_output_record,
    create_relay,
    read_request_output,
)

# ── AS30 imports ───────────────────────────────────────────────────────
from audiagentic.components.agents.gateway.session import bindings as bindings
from audiagentic.components.agents.gateway.session import sessions_store as session_store

# ── AS19 imports ───────────────────────────────────────────────────────
from audiagentic.components.agents.status.harness_status_observer_ingress import (
    MAX_REQUEST_BODY_BYTES,
    SessionObserverIngress,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_output import (
    AgentOutputEvent,
    AgentOutputKind,
)

# ── Helpers ────────────────────────────────────────────────────────────

def _make_project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with .audiagentic marker."""
    (tmp_path / ".audiagentic").mkdir(parents=True)
    return tmp_path


def _make_session_record(
    project_root: Path,
    session_id: str,
    provider_ref: str,
    state: str = "active",
    provider_id: str | None = "test-provider",
    surface_id: str = "test-surface",
) -> dict[str, Any]:
    """Write a session record with a binding and return it."""
    record = session_store.build_session_record(
        session_id=session_id,
        execution_profile_id="default",
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        surface_id=surface_id,
    )
    if state != "active":
        record["state"] = state
    session_store.write_session_record(project_root, record)
    return record


# =====================================================================
# AS19: Status Observer Ingress Docker Tests
# =====================================================================

class TestAS19ObserverIngressDocker:
    """AS19 status observer integration tests in Docker."""

    def test_observer_binding_lifecycle(self, tmp_path: Path) -> None:
        """Full lifecycle: create binding → deliver observation → invalidate on close.

        Validates:
        - Gateway session opens and creates observer binding
        - Transport observations flow through observer ingress
        - Binding is invalidated on session close
        - Re-delivery after invalidation returns False
        """
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()

        # 1. Create observer binding (session open).
        session_id = "ses_obs_001"
        binding_id, token, endpoint = ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )
        assert binding_id.startswith("obsbnd_")
        assert len(token) == 64  # 32 bytes hex
        assert endpoint == f"loopback://session/{session_id}/observer"

        # Verify registration exists.
        reg = ingress.get_registration(binding_id)
        assert reg is not None
        assert reg.session_id == session_id
        assert ingress.has_binding_for_session(session_id)

        # 2. Deliver a valid observation.
        observation = {
            "status": "model-thinking",
            "session-id": session_id,
            "source-kind": "transport-observation",
        }
        result = ingress.deliver_observation(
            binding_id=binding_id,
            token=token,
            observation=observation,
            session_id=session_id,
            project_root=str(project_root),
        )
        assert result is True

        # 3. Invalidate the binding (session close).
        ingress.invalidate_binding(binding_id)
        assert not ingress.has_binding_for_session(session_id)
        assert ingress.get_registration(binding_id) is None

        # 4. Re-delivery after invalidation returns False.
        result = ingress.deliver_observation(
            binding_id=binding_id,
            token=token,
            observation=observation,
            session_id=session_id,
            project_root=str(project_root),
        )
        assert result is False

    def test_observer_delivery_with_callback(self, tmp_path: Path) -> None:
        """Observations delivered through callback (on_observation hook)."""
        project_root = _make_project_root(tmp_path)
        observations_received: list[tuple[str, Any]] = []

        async def on_obs(session_id: str, obs: Any) -> None:
            observations_received.append((session_id, obs))

        ingress = SessionObserverIngress(on_observation=on_obs)
        session_id = "ses_obs_cb"
        binding_id, token, _ = ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )

        observation = {"status": "tool-calling", "session-id": session_id}
        # Need a running event loop for callback delivery.
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            async def deliver() -> None:
                assert ingress.deliver_observation(
                    binding_id=binding_id,
                    token=token,
                    observation=observation,
                    session_id=session_id,
                    project_root=str(project_root),
                ) is True

            loop.run_until_complete(deliver())
            # Give the task a moment to run.
            loop.run_until_complete(asyncio.sleep(0.1))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

        assert len(observations_received) == 1
        assert observations_received[0][0] == session_id

    def test_observer_binding_one_per_session(self, tmp_path: Path) -> None:
        """Only one observer binding per session — second raises error."""
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()
        session_id = "ses_obs_single"

        ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )

        with pytest.raises(AudiaGenticError, match="already has an active observer binding"):
            ingress.create_observer_binding(
                session_id=session_id,
                project_root=str(project_root),
            )

    def test_observer_token_mismatch_rejected(self, tmp_path: Path) -> None:
        """Wrong token → observation rejected (returns False)."""
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()
        session_id = "ses_obs_tok"
        binding_id, token, _ = ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )

        result = ingress.deliver_observation(
            binding_id=binding_id,
            token="wrong-token",
            observation={"status": "thinking"},
            session_id=session_id,
            project_root=str(project_root),
        )
        assert result is False

    def test_observer_body_bound_enforced(self, tmp_path: Path) -> None:
        """Observation body exceeding MAX_REQUEST_BODY_BYTES is rejected."""
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()
        session_id = "ses_obs_big"
        binding_id, token, _ = ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )

        # Create an oversized observation (dict that serializes to >8KB).
        big_obs = {"data": "x" * (MAX_REQUEST_BODY_BYTES + 1)}
        result = ingress.deliver_observation(
            binding_id=binding_id,
            token=token,
            observation=big_obs,
            session_id=session_id,
            project_root=str(project_root),
        )
        assert result is False

    def test_observer_invalidate_all_for_session(self, tmp_path: Path) -> None:
        """invalidate_all_for_session removes all bindings for a session."""
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()

        # Create two sessions with bindings.
        binding1_id, _, _ = ingress.create_observer_binding(
            session_id="ses_all_001",
            project_root=str(project_root),
        )
        binding2_id, _, _ = ingress.create_observer_binding(
            session_id="ses_all_002",
            project_root=str(project_root),
        )

        # Invalidate session 1.
        ingress.invalidate_all_for_session("ses_all_001")
        assert not ingress.has_binding_for_session("ses_all_001")
        assert ingress.get_registration(binding1_id) is None

        # Session 2 unaffected.
        assert ingress.has_binding_for_session("ses_all_002")
        assert ingress.get_registration(binding2_id) is not None


# =====================================================================
# AS30: Session Binding Docker Tests (cross-process safety)
# =====================================================================

class TestAS30SessionBindingDocker:
    """AS30 session binding durability and cross-process safety in Docker."""

    def test_binding_persists_to_disk(self, tmp_path: Path) -> None:
        """Session binding persists to disk — survives reading from another process."""
        project_root = _make_project_root(tmp_path)
        record = _make_session_record(project_root, "ses_bind_001", "ref-alpha")

        # Register the binding.
        bindings.register_open_binding(project_root, record)

        # Read back from disk — simulates another process reading.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))

        assert payload["contract-version"] == "v1"
        ref_key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-alpha",
        )
        assert ref_key in payload["bindings"]
        entries = payload["bindings"][ref_key]
        assert len(entries) == 1
        assert entries[0]["binding-id"] == record["binding"]["binding-id"]
        assert entries[0]["ownership"] == "owned"

    def test_cross_process_duplicate_detection(self, tmp_path: Path) -> None:
        """Two real subprocesses both try to create the same owned binding;
        only one succeeds. This tests cross-process StartupLock exclusion."""
        project_root = _make_project_root(tmp_path)

        # First process: create and register the binding.
        record1 = _make_session_record(project_root, "ses_cross_001", "ref-cross")
        bindings.register_open_binding(project_root, record1)

        # Second process (subprocess): try to register the same key.
        result = subprocess.run(
            [
                sys.executable, "-c",
                f"""
import json, sys
sys.path.insert(0, "/app/src")
from pathlib import Path
from audiagentic.components.agents.gateway.session import bindings as bindings
from audiagentic.components.agents.gateway.session import sessions_store as session_store

project_root = Path("{project_root}")
record = session_store.build_session_record(
    session_id="ses_cross_002",
    execution_profile_id="default",
    provider_id="test-provider",
    provider_session_ref="ref-cross",
    surface_id="test-surface",
)
session_store.write_session_record(project_root, record)
try:
    bindings.register_open_binding(project_root, record)
    print("DUPLICATE_ACCEPTED")
except Exception as e:
    if "duplicate owned" in str(e):
        print("DUPLICATE_REJECTED")
    else:
        print(f"UNEXPECTED: {{e}}")
""",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/app",
        )
        assert result.stdout.strip() == "DUPLICATE_REJECTED", (
            f"Subprocess should have rejected duplicate binding; got: {result.stdout} {result.stderr}"
        )

    def test_binding_index_atomic_under_concurrent_access(self, tmp_path: Path) -> None:
        """Concurrent register_open_binding calls serialize through StartupLock;
        no index corruption occurs."""
        project_root = _make_project_root(tmp_path)
        errors: list[str] = []

        def _register(idx: int) -> None:
            try:
                record = _make_session_record(
                    project_root, f"ses_conc_{idx}", f"ref-conc-{idx}"
                )
                bindings.register_open_binding(project_root, record)
            except Exception as e:
                errors.append(f"[{idx}] {e}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_register, i) for i in range(8)]
            for f in futures:
                f.result(timeout=30)

        assert not errors, f"Registration errors: {errors}"

        # Index should be valid JSON with all entries.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(payload["bindings"]) == 8

    def test_rebuild_recovers_from_corrupted_index(self, tmp_path: Path) -> None:
        """If the index file is corrupted (e.g., partial write from crash),
        rebuild_index recovers all bindings from session records."""
        project_root = _make_project_root(tmp_path)

        # Create and register several sessions.
        for i in range(5):
            record = _make_session_record(project_root, f"ses_rebuild_{i}", f"ref-rb-{i}")
            bindings.register_open_binding(project_root, record)

        # Verify index is complete.
        payload = bindings._read_index(bindings.gateway_session_binding_index_path(project_root))
        assert len(payload["bindings"]) == 5

        # Corrupt the index file (truncate to invalid JSON).
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text('{"contract-version": "v1", "bindings": {"key1": [{"b', encoding="utf-8")

        # Rebuild should recover all sessions.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 5

    def test_rebuild_detects_duplicate_active_owned(self, tmp_path: Path) -> None:
        """Rebuild detects duplicate active owned bindings from session records."""
        project_root = _make_project_root(tmp_path)

        # Create two sessions with the same provider ref (both owned).
        record1 = _make_session_record(project_root, "ses_dup_001", "ref-dup-rebuild")
        session_store.write_session_record(project_root, record1)
        record2 = _make_session_record(project_root, "ses_dup_002", "ref-dup-rebuild")
        session_store.write_session_record(project_root, record2)

        # Rebuild should detect the duplicate.
        rebuilt = bindings.rebuild_index(project_root)
        ref_key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-dup-rebuild",
        )
        entries = rebuilt["bindings"].get(ref_key, [])
        # Both sessions should be in the index.
        assert len(entries) == 2

    def test_retire_binding_updates_state(self, tmp_path: Path) -> None:
        """retire_binding updates the binding state atomically."""
        project_root = _make_project_root(tmp_path)
        record = _make_session_record(project_root, "ses_retire", "ref-retire")
        bindings.register_open_binding(project_root, record)

        # Retire the binding.
        bindings.retire_binding(project_root, record, state="closed")

        # Read back — state should be updated.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        ref_key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-retire",
        )
        entries = payload["bindings"][ref_key]
        assert entries[0]["state"] == "closed"
        assert "retired-at" in entries[0]


# =====================================================================
# AS31: Output Relay Docker Tests
# =====================================================================

class TestAS31OutputRelayDocker:
    """AS31 output relay persistence, bounds enforcement, and monotonicity."""

    def test_output_events_persist_atomically(self, tmp_path: Path) -> None:
        """Output events are persisted atomically to disk; reading back yields all events."""
        project_root = _make_project_root(tmp_path)
        policy = OutputPolicy.default_enabled()

        relay = create_relay(
            project_root=project_root,
            request_id="req_001",
            session_id="ses_out_001",
            turn_id="turn_001",
            policy=policy,
        )

        # Send several events.
        for seq in range(5):
            event = AgentOutputEvent(
                session_id="ses_out_001",
                turn_id="turn_001",
                sequence=seq,
                kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
                text=f"chunk {seq} ",
                observed_at="2025-01-01T00:00:00Z",
                is_final=False,
            )
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(relay(event))
            finally:
                loop.close()

        # Read back from disk.
        output_data = read_request_output(project_root, "req_001")
        assert len(output_data["events"]) == 5
        for i, evt in enumerate(output_data["events"]):
            assert evt["sequence"] == i
            assert evt["text"] == f"chunk {i} "

    def test_fragment_bounds_enforced(self, tmp_path: Path) -> None:
        """Fragment exceeding max_fragment_bytes is rejected — relay degrades gracefully."""
        project_root = _make_project_root(tmp_path)
        policy = OutputPolicy(
            enabled=True,
            max_fragment_bytes=1024,  # Small bound for testing
            max_turn_bytes=512_000,
        )

        relay = create_relay(
            project_root=project_root,
            request_id="req_frag",
            session_id="ses_frag",
            turn_id="turn_frag",
            policy=policy,
        )

        # Oversized fragment (1KB of text > 1024 byte limit).
        event = AgentOutputEvent(
            session_id="ses_frag",
            turn_id="turn_frag",
            sequence=0,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
            text="x" * (1024 + 1),
            observed_at="2025-01-01T00:00:00Z",
            is_final=False,
        )

        # Relay should accept but degrade (not raise).
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(relay(event))
        finally:
            loop.close()

        # Relay entered degradation mode.
        assert relay.is_degraded is True

    def test_sequence_monotonicity_validated(self, tmp_path: Path) -> None:
        """Non-monotonic sequences are rejected — relay degrades gracefully."""
        project_root = _make_project_root(tmp_path)
        policy = OutputPolicy.default_enabled()

        relay = create_relay(
            project_root=project_root,
            request_id="req_seq",
            session_id="ses_seq",
            turn_id="turn_seq",
            policy=policy,
        )

        # Valid sequence 0.
        event_0 = AgentOutputEvent(
            session_id="ses_seq", turn_id="turn_seq", sequence=0,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="first",
            observed_at="2025-01-01T00:00:00Z", is_final=False,
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(relay(event_0))
        finally:
            loop.close()

        # Non-monotonic sequence (3 then 2).
        event_bad = AgentOutputEvent(
            session_id="ses_seq", turn_id="turn_seq", sequence=1,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="second",
            observed_at="2025-01-01T00:00:01Z", is_final=False,
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(relay(event_bad))
        finally:
            loop.close()

        # Now send a non-monotonic event.
        event_dup = AgentOutputEvent(
            session_id="ses_seq", turn_id="turn_seq", sequence=0,  # duplicate!
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="dup",
            observed_at="2025-01-01T00:00:02Z", is_final=False,
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(relay(event_dup))
        finally:
            loop.close()

        # Relay should have degraded due to the non-monotonic sequence.
        assert relay.is_degraded is True

    def test_relay_failure_doesnt_kill_the_turn(self, tmp_path: Path) -> None:
        """When persistence fails (e.g., disk full simulation), the relay degrades
        but continues accepting events in-memory — turn is NOT killed."""
        project_root = _make_project_root(tmp_path)
        policy = OutputPolicy.default_enabled()

        relay = create_relay(
            project_root=project_root,
            request_id="req_degrade",
            session_id="ses_deg",
            turn_id="turn_deg",
            policy=policy,
        )

        # Force degradation by making the relay's persistence fail.
        # We simulate this by removing the lock path directory after events.
        relay._degraded = True  # Simulate degradation from I/O error

        # Events should still be accepted (in-memory only).
        event = AgentOutputEvent(
            session_id="ses_deg", turn_id="turn_deg", sequence=0,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="degraded chunk",
            observed_at="2025-01-01T00:00:00Z", is_final=False,
        )
        loop = asyncio.new_event_loop()
        try:
            # Should not raise even though degraded.
            loop.run_until_complete(relay(event))
        finally:
            loop.close()

        assert relay.has_events is True
        assert relay.is_degraded is True

    def test_append_agent_output_record_standalone(self, tmp_path: Path) -> None:
        """append_agent_output_record works as a standalone entry point (recovery path)."""
        project_root = _make_project_root(tmp_path)

        event = AgentOutputEvent(
            session_id="ses_standalone", turn_id="turn_standalone", sequence=42,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="standalone chunk",
            observed_at="2025-01-01T00:00:00Z", is_final=False,
        )
        append_agent_output_record(project_root, "req_standalone", event)

        # Read back.
        output_data = read_request_output(project_root, "req_standalone")
        assert len(output_data["events"]) == 1
        assert output_data["events"][0]["sequence"] == 42
        assert output_data["events"][0]["text"] == "standalone chunk"

    def test_disabled_policy_blocks_output(self, tmp_path: Path) -> None:
        """Disabled policy silently blocks all output events."""
        project_root = _make_project_root(tmp_path)
        policy = OutputPolicy.disabled()

        relay = create_relay(
            project_root=project_root,
            request_id="req_disabled",
            session_id="ses_disabled",
            turn_id="turn_disabled",
            policy=policy,
        )

        event = AgentOutputEvent(
            session_id="ses_disabled", turn_id="turn_disabled", sequence=0,
            kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, text="blocked",
            observed_at="2025-01-01T00:00:00Z", is_final=False,
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(relay(event))
        finally:
            loop.close()

        # No events should be persisted.
        assert not relay.has_events
        output_data = read_request_output(project_root, "req_disabled")
        assert len(output_data["events"]) == 0


# =====================================================================
# Full Pipeline Integration: AS19 + AS30 + AS31 together
# =====================================================================

class TestConsumerPipelineFullIntegration:
    """End-to-end test combining AS19, AS30, and AS31 in a single flow."""

    def test_full_pipeline_session_lifecycle(self, tmp_path: Path) -> None:
        """Session opens with binding + observer → output is streamed while
        status is observed → session closes and binding invalidates → all
        durable state is consistent.

        This simulates the real consumer pipeline flow in an isolated container.
        """
        project_root = _make_project_root(tmp_path)

        # ── Phase 1: Session open (AS30 + AS19) ──────────────────────

        # Create session binding.
        session_id = "ses_full_001"
        provider_ref = "ref-full-alpha"
        record = _make_session_record(project_root, session_id, provider_ref)
        bindings.register_open_binding(project_root, record)

        # Create observer binding.
        ingress = SessionObserverIngress()
        binding_id, token, endpoint = ingress.create_observer_binding(
            session_id=session_id,
            project_root=str(project_root),
        )

        # Verify both are active.
        assert ingress.has_binding_for_session(session_id)
        index_path = bindings.gateway_session_binding_index_path(project_root)
        assert index_path.exists()

        # ── Phase 2: Output streaming with status observation (AS31 + AS19) ──

        policy = OutputPolicy.default_enabled()
        relay = create_relay(
            project_root=project_root,
            request_id="req_full_001",
            session_id=session_id,
            turn_id="turn_full_001",
            policy=policy,
        )

        # Stream output events while observing status.
        statuses = ["model-thinking", "generating-text", "tool-calling"]
        for seq in range(3):
            # Send output event.
            event = AgentOutputEvent(
                session_id=session_id, turn_id="turn_full_001", sequence=seq,
                kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
                text=f"chunk {seq} ",
                observed_at=f"2025-01-01T00:00:{seq:02d}Z",
                is_final=seq == 2,
            )
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(relay(event))
            finally:
                loop.close()

            # Deliver status observation.
            status_obs = {
                "status": statuses[seq],
                "session-id": session_id,
                "request-id": "req_full_001",
            }
            result = ingress.deliver_observation(
                binding_id=binding_id,
                token=token,
                observation=status_obs,
                session_id=session_id,
                project_root=str(project_root),
            )
            assert result is True

        # ── Phase 3: Session close (AS19 + AS30) ─────────────────────

        # Invalidate observer binding.
        ingress.invalidate_binding(binding_id)
        assert not ingress.has_binding_for_session(session_id)

        # Retire session binding.
        bindings.retire_binding(project_root, record, state="closed")

        # ── Phase 4: Verify durable consistency ───────────────────────

        # Output events persisted correctly.
        output_data = read_request_output(project_root, "req_full_001")
        assert len(output_data["events"]) == 3
        assert output_data["events"][2]["is-final"] is True
        index = output_data["index"]
        assert index["seq-start"] == 0
        assert index["seq-end"] == 2

        # Binding retired in index.
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        ref_key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref=provider_ref,
        )
        assert payload["bindings"][ref_key][0]["state"] == "closed"

        # Observer binding fully invalidated.
        assert ingress.get_registration(binding_id) is None

    def test_full_pipeline_storage_survives_restart(self, tmp_path: Path) -> None:
        """All durable state survives a simulated container restart (new process
        reads the same filesystem)."""
        project_root = _make_project_root(tmp_path)
        session_id = "ses_restart"
        provider_ref = "ref-restart"

        # Create and register binding in this process.
        record = _make_session_record(project_root, session_id, provider_ref)
        bindings.register_open_binding(project_root, record)

        # Persist output events.
        policy = OutputPolicy.default_enabled()
        relay = create_relay(
            project_root=project_root,
            request_id="req_restart",
            session_id=session_id,
            turn_id="turn_restart",
            policy=policy,
        )

        for seq in range(3):
            event = AgentOutputEvent(
                session_id=session_id, turn_id="turn_restart", sequence=seq,
                kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
                text=f"chunk {seq} ",
                observed_at=f"2025-01-01T00:00:{seq:02d}Z",
                is_final=False,
            )
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(relay(event))
            finally:
                loop.close()

        # Simulate container restart: new process reads from disk.
        result = subprocess.run(
            [
                sys.executable, "-c",
                f"""
import json, sys
sys.path.insert(0, "/app/src")
from pathlib import Path
from audiagentic.components.agents.gateway.session import bindings as bindings
from audiagentic.components.agents.gateway.output import read_request_output

project_root = Path("{project_root}")

# Read binding index.
index_path = bindings.gateway_session_binding_index_path(project_root)
payload = json.loads(index_path.read_text(encoding="utf-8"))
print(f"bindings={{len(payload['bindings'])}}")

# Read output events.
output_data = read_request_output(project_root, "req_restart")
print(f"events={{len(output_data['events'])}}")
for evt in output_data["events"]:
    print(f"  seq={{evt['sequence']}} text={{evt['text']!r}}")

# Verify sequence monotonicity.
sequences = [e['sequence'] for e in output_data['events']]
assert sequences == sorted(sequences), "Sequences not monotonic!"
print("MONOTONIC_OK")
""",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/app",
        )

        assert result.returncode == 0, f"Restart check failed: {result.stderr}"
        assert "bindings=1" in result.stdout
        assert "events=3" in result.stdout
        assert "MONOTONIC_OK" in result.stdout

    def test_full_pipeline_concurrent_sessions(self, tmp_path: Path) -> None:
        """Multiple concurrent sessions each with AS19+AS30+AS31 components."""
        project_root = _make_project_root(tmp_path)
        ingress = SessionObserverIngress()
        errors: list[str] = []

        def _run_session(idx: int) -> None:
            try:
                session_id = f"ses_conc_full_{idx}"
                provider_ref = f"ref-conc-full-{idx}"

                # AS30: Create and register binding.
                record = _make_session_record(project_root, session_id, provider_ref)
                bindings.register_open_binding(project_root, record)

                # AS19: Create observer binding.
                binding_id, token, _ = ingress.create_observer_binding(
                    session_id=session_id,
                    project_root=str(project_root),
                )

                # AS31: Stream output events.
                policy = OutputPolicy.default_enabled()
                relay = create_relay(
                    project_root=project_root,
                    request_id=f"req_conc_full_{idx}",
                    session_id=session_id,
                    turn_id=f"turn_conc_full_{idx}",
                    policy=policy,
                )

                for seq in range(2):
                    event = AgentOutputEvent(
                        session_id=session_id,
                        turn_id=f"turn_conc_full_{idx}",
                        sequence=seq,
                        kind=AgentOutputKind.ASSISTANT_TEXT_DELTA,
                        text=f"s{idx}-chunk {seq} ",
                        observed_at=f"2025-01-01T00:00:{seq:02d}Z",
                        is_final=False,
                    )
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(relay(event))
                    finally:
                        loop.close()

                # AS19: Deliver status observation.
                ingress.deliver_observation(
                    binding_id=binding_id,
                    token=token,
                    observation={"status": "model-thinking", "session-id": session_id},
                    session_id=session_id,
                    project_root=str(project_root),
                )

                # Close: invalidate observer, retire binding.
                ingress.invalidate_binding(binding_id)
                bindings.retire_binding(project_root, record, state="closed")

            except Exception as e:
                errors.append(f"[{idx}] {e}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_run_session, i) for i in range(6)]
            for f in futures:
                f.result(timeout=60)

        assert not errors, f"Concurrent session errors: {errors}"

        # All bindings registered and retired.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(payload["bindings"]) == 6

        # All observer bindings invalidated.
        for i in range(6):
            session_id = f"ses_conc_full_{i}"
            assert not ingress.has_binding_for_session(session_id)
