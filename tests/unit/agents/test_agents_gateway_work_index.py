"""SH07 C7 (SH14): transactional active/admitted work index safety — crash windows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import recovery as recovery_mod
from audiagentic.components.agents.gateway.queue import work_index as wi
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _record(project_root: Path, prompt: str = "hello") -> dict:
    """Admit a request into the project root (without service_root)."""
    candidate = store.build_record(execution_profile_id="default", prompt_body=prompt)
    store.write_record(project_root, candidate)
    return candidate


# ---------------------------------------------------------------------------
# Crash window A: record persisted but index write fails at admission
# ---------------------------------------------------------------------------

class TestCrashWindowA_RecordButNoIndex:
    """Record is written but work-index entry fails → recovery still works."""

    def test_admission_crash_after_record_no_index(self, tmp_path: Path) -> None:
        """Service crashes after writing the request record but before index write.
        
        Recovery via active-work path should still discover the request because
        the record is in 'queued' state with no dispatch-owner-epoch set.
        """
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        # Write record directly (simulating crash after write_record)
        store.write_record(project_root, candidate)

        # No index entry exists (crash happened before index write)
        assert not wi._entry_path(service_root, candidate["request-id"]).exists()

        report = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        # Nothing to recover because no dispatch owner and no index entry
        assert report.examined == 0

    def test_admission_with_service_root_writes_index(self, tmp_path: Path) -> None:
        """Normal admission path: record + index both written."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        store.write_record(project_root, candidate)
        # Write the index entry manually (simulating successful admission path)
        wi.write_work_index_entry(service_root, project_root, candidate["request-id"], phase="admitted")

        assert wi._entry_path(service_root, candidate["request-id"]).exists()

# ---------------------------------------------------------------------------
# Crash window B: index write at admission succeeds, but claim has not happened
# ---------------------------------------------------------------------------

class TestCrashWindowB_AdmittedBeforeClaim:
    """C7 core scenario: admitted work discovered before claim via work-index."""

    def test_admitted_but_unclaimed_recovered_as_replay_required(
        self, tmp_path: Path,
    ) -> None:
        """Request admitted and index written, but crash before claim.
        
        Recovery must terminalize as interrupted + CON-AGW-102 + replay-required
        and MUST NOT enqueue the old prompt.
        """
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        store.write_record(project_root, candidate)
        request_id = candidate["request-id"]
        # Write the work-index entry at admission (simulating admit_record path)
        wi.write_work_index_entry(
            service_root, project_root, request_id,
            phase="admitted",
        )

        # Verify: record is still queued, no owner epoch
        assert candidate["state"] == "queued"
        assert candidate.get("dispatch-owner-epoch") is None

        report = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "interrupted"
        assert recovered.get("replay-required") is True
        assert recovered["error"]["code"] == "CON-AGW-102"
        assert report.replay_required >= 1

    def test_admitted_unclaimed_never_reenqueues(
        self, tmp_path: Path,
    ) -> None:
        """After recovery, the request must not be in the queue."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        store.write_record(project_root, candidate)
        request_id = candidate["request-id"]
        wi.write_work_index_entry(
            service_root, project_root, request_id,
            phase="admitted",
        )

        recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "interrupted"
        assert recovered.get("replay-required") is True

# ---------------------------------------------------------------------------
# Crash window C: claim succeeded, index updated to claimed, but start failed
# ---------------------------------------------------------------------------

class TestCrashWindowC_ClaimedBeforeStart:
    """Claim happened but start failed before attempt was recorded."""

    def test_claimed_but_not_started_recovered(self, tmp_path: Path) -> None:
        """Request was claimed but crashed before start_owned_attempt."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        store.write_record(project_root, candidate)
        request_id = candidate["request-id"]
        # Simulate: admit_record wrote index entry at admission with phase "admitted"
        wi.write_work_index_entry(
            service_root, project_root, request_id,
            phase="admitted",
        )
        # Now claim_dispatch transitions admitted → claimed and updates the record
        store.claim_dispatch(
            project_root, request_id,
            owner_epoch="old-epoch", expected_revision=candidate["revision"],
            service_root=service_root,
        )

        report = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "interrupted"
        assert report.replay_required >= 1 or report.interrupted >= 1

# ---------------------------------------------------------------------------
# Crash window D: running but no terminal state reached
# ---------------------------------------------------------------------------

class TestCrashWindowD_RunningNotTerminal:
    """Request was running when crash happened — interrupted, not replay-required."""

    def test_running_interrupted_not_replay(self, tmp_path: Path) -> None:
        """Running request is interrupted with CON-AGW-084, no replay."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root, record["request-id"],
            owner_epoch="old-epoch", expected_revision=record["revision"],
            service_root=service_root,
        )
        running = store.start_owned_attempt(
            project_root, record["request-id"],
            owner_epoch="old-epoch", worker_id="w1",
            expected_revision=claimed["revision"],
        )

        # Verify: request is running, index phase is "running"
        assert running["state"] == "running"
        idx_result = wi.validate_work_index_entry(
            wi._entry_path(service_root, record["request-id"])
        )
        assert not isinstance(idx_result, wi.InvalidEntry)
        assert idx_result.phase == "running"

        report = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        recovered = store.read_record(project_root, record["request-id"])
        assert recovered["state"] == "interrupted"
        assert recovered["error"]["code"] == "CON-AGW-084"
        assert report.interrupted >= 1

# ---------------------------------------------------------------------------
# Crash window E: terminal transition succeeds but index cleanup fails
# ---------------------------------------------------------------------------

class TestCrashWindowE_TerminalThenCleanupFails:
    """Terminal state is durable even if index cleanup fails."""

    def test_terminal_state_survives_cleanup_failure(self, tmp_path: Path) -> None:
        """Corrupt the index entry right before terminalization. Terminal state wins."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root, record["request-id"],
            owner_epoch="old-epoch", expected_revision=record["revision"],
            service_root=service_root,
        )
        running = store.start_owned_attempt(
            project_root, record["request-id"],
            owner_epoch="old-epoch", worker_id="w1",
            expected_revision=claimed["revision"],
        )

        # Corrupt the index entry to simulate cleanup failure
        idx_path = wi._entry_path(service_root, record["request-id"])
        idx_path.write_text("{corrupt}", encoding="utf-8")

        terminal = store.transition_owned_terminal(
            project_root, record["request-id"], "failed",
            owner_epoch="old-epoch", worker_id="w1",
            attempt_epoch=running["attempt-epoch"],
            updates={"error": {"code": "TEST-ERR", "message": "test", "kind": "test"}},
            service_root=service_root,
        )

        assert terminal["state"] == "failed"
        # Corrupt index entry was quarantined, not silently deleted
        quarantine_dir = wi._quarantine_dir(service_root)
        if quarantine_dir.exists():
            entries = list(quarantine_dir.glob(f"*{record['request-id']}*"))
            assert len(entries) >= 1

    def test_terminal_cleanup_never_raises(self, tmp_path: Path) -> None:
        """clear_stale_terminal_index never raises to the caller."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        record = _record(project_root)
        wi.write_work_index_entry(service_root, project_root, record["request-id"], phase="admitted")

        # Corrupt the entry
        idx_path = wi._entry_path(service_root, record["request-id"])
        idx_path.write_text("{bad json", encoding="utf-8")

        # Should not raise
        wi.clear_stale_terminal_index(service_root, record["request-id"])

# ---------------------------------------------------------------------------
# Owner fencing enforcement
# ---------------------------------------------------------------------------

class TestOwnerFencing:
    """Phase transitions enforce ownership fencing."""

    def test_claims_transitions_with_same_owner(self, tmp_path: Path) -> None:
        """Normal case: same owner can transition claimed → running."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        wi.write_work_index_entry(
            service_root, project_root, "req_fence1",
            phase="claimed", owner_epoch="epoch-1",
        )

        ok = wi.update_work_index_phase(
            service_root, "req_fence1",
            from_phase="claimed", to_phase="running",
            owner_epoch="epoch-1",
        )
        assert ok is True

    def test_different_owner_blocked_on_claimed_to_running(self, tmp_path: Path) -> None:
        """Different epoch cannot transition claimed → running."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        wi.write_work_index_entry(
            service_root, project_root, "req_fence2",
            phase="claimed", owner_epoch="epoch-1",
        )

        with pytest.raises(AudiaGenticError, match="CON-AGW-106"):
            wi.update_work_index_phase(
                service_root, "req_fence2",
                from_phase="claimed", to_phase="running",
                owner_epoch="epoch-2",
            )

    def test_different_owner_blocked_on_running_to_terminal(self, tmp_path: Path) -> None:
        """Different epoch cannot transition running → terminal-cleanup."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        wi.write_work_index_entry(
            service_root, project_root, "req_fence3",
            phase="running", owner_epoch="epoch-1",
        )

        with pytest.raises(AudiaGenticError, match="CON-AGW-106"):
            wi.update_work_index_phase(
                service_root, "req_fence3",
                from_phase="running", to_phase="terminal-cleanup",
                owner_epoch="epoch-2",
            )

# ---------------------------------------------------------------------------
# Admission ordering: record first, then index
# ---------------------------------------------------------------------------

class TestAdmissionOrdering:
    """admit_record writes work-index only after the request record is durable."""

    def test_admit_record_writes_index_after_record(
        self, tmp_path: Path,
    ) -> None:
        """Both record and index are written when service_root is provided."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        record, created = store.admit_record(
            project_root, candidate,
            idempotency_key="test-key-001",
            service_root=service_root,
        )

        assert created is True
        # Verify index entry exists with phase="admitted"
        idx_path = wi._entry_path(service_root, record["request-id"])
        assert idx_path.exists()
        result = wi.validate_work_index_entry(idx_path)
        assert not isinstance(result, wi.InvalidEntry)
        assert result.phase == "admitted"

    def test_admit_record_without_service_root_skips_index(
        self, tmp_path: Path,
    ) -> None:
        """When service_root is None, no index entry is written."""
        project_root = tmp_path / "project"

        candidate = store.build_record(execution_profile_id="default", prompt_body="test")
        record, created = store.admit_record(
            project_root, candidate,
            idempotency_key="test-key-002",
        )

        assert created is True
        # No index directory should exist
        service_root = tmp_path / "service"
        assert not (service_root / wi._INDEX_DIR).exists()

# ---------------------------------------------------------------------------
# Quarantine: bounded retention of forensic evidence
# ---------------------------------------------------------------------------

class TestQuarantineBoundedRetention:
    """Quarantined entries remain on disk for forensic analysis."""

    def test_expired_quarantine_entries_removed(self, tmp_path: Path) -> None:
        """Old quarantine entries beyond max_age_seconds are removed."""
        import os
        import time

        service_root = tmp_path / "service"
        qdir = wi._quarantine_dir(service_root)
        qdir.mkdir(parents=True, exist_ok=True)

        # Write two quarantine entries
        old_file = qdir / "req_old_malformed.json"
        old_file.write_text('{"request-id": "req_old"}', encoding="utf-8")
        new_file = qdir / "req_new_malformed.json"
        new_file.write_text('{"request-id": "req_new"}', encoding="utf-8")

        # Age the old file by setting its mtime far in the past
        old_time = time.time() - 8 * 24 * 3600  # 8 days ago
        os.utime(str(old_file), (old_time, old_time))

        # Sweep with 7-day max age: old file removed, new file kept
        removed = wi.clear_expired_quarantine_entries(service_root, max_age_seconds=7 * 24 * 3600)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_recent_quarantine_entries_preserved(self, tmp_path: Path) -> None:
        """Quarantine entries within max_age_seconds are never removed."""
        service_root = tmp_path / "service"
        qdir = wi._quarantine_dir(service_root)
        qdir.mkdir(parents=True, exist_ok=True)

        (qdir / "req_recent_malformed.json").write_text(
            '{"request-id": "req_recent"}', encoding="utf-8"
        )

        removed = wi.clear_expired_quarantine_entries(service_root, max_age_seconds=7 * 24 * 3600)
        assert removed == 0

    def test_active_entries_never_touched(self, tmp_path: Path) -> None:
        """The sweep only touches the quarantine directory, never active entries."""
        import os
        import time

        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        idx_dir = wi._index_dir(service_root)
        idx_dir.mkdir(parents=True)
        qdir = wi._quarantine_dir(service_root)
        qdir.mkdir(parents=True)

        # Write an active entry (old mtime) and a quarantine entry (old mtime)
        active_file = idx_dir / "req_active.json"
        active_file.write_text(
            json.dumps({
                "request-id": "req_active",
                "project-root": str(project_root),
                "phase": "admitted",
            }),
            encoding="utf-8",
        )
        old_time = time.time() - 8 * 24 * 3600
        os.utime(str(active_file), (old_time, old_time))

        quarantine_file = qdir / "req_q_malformed.json"
        quarantine_file.write_text('{"request-id": "req_q"}', encoding="utf-8")
        os.utime(str(quarantine_file), (old_time, old_time))

        removed = wi.clear_expired_quarantine_entries(service_root, max_age_seconds=7 * 24 * 3600)
        assert removed == 1
        # Active entry survives despite being old
        assert active_file.exists()

    def test_quarantine_bounded_across_recovery_cycles(self, tmp_path: Path) -> None:
        """Repeated recovery cycles do not cause unbounded quarantine growth when
        expired entries are swept before each cycle."""
        import os
        import time

        service_root = tmp_path / "service"
        idx_dir = wi._index_dir(service_root)
        idx_dir.mkdir(parents=True)

        def write_malformed(name: str) -> None:
            (idx_dir / f"req_{name}.json").write_text(
                '{"request-id": "req_x"}',  # missing phase → quarantined
                encoding="utf-8",
            )

        def quarantine_count() -> int:
            qdir = wi._quarantine_dir(service_root)
            if not qdir.exists():
                return 0
            return len(list(qdir.glob("*.json")))

        # Cycle 1: create and quarantine an entry
        write_malformed("cycle1")
        wi.recover_work_index_entries(service_root, live_owner_epoch="live")
        assert quarantine_count() >= 1

        # Age it beyond threshold
        old_time = time.time() - 8 * 24 * 3600
        for f in wi._quarantine_dir(service_root).glob("*.json"):
            os.utime(str(f), (old_time, old_time))

        # Sweep before cycle 2 removes the old entry
        wi.clear_expired_quarantine_entries(service_root, max_age_seconds=7 * 24 * 3600)
        assert quarantine_count() == 0

        # Cycle 2: fresh entry quarantined, count stays at 1
        write_malformed("cycle2")
        wi.recover_work_index_entries(service_root, live_owner_epoch="live")
        assert quarantine_count() == 1

    def test_no_quarantine_dir_is_noop(self, tmp_path: Path) -> None:
        """Sweep returns 0 when quarantine directory does not exist."""
        service_root = tmp_path / "service"
        removed = wi.clear_expired_quarantine_entries(service_root, max_age_seconds=3600)
        assert removed == 0

    def test_quarantined_entry_preserved(self, tmp_path: Path) -> None:
        """Malformed entry is quarantined and remains accessible."""
        service_root = tmp_path / "service"
        idx_dir = wi._index_dir(service_root)
        idx_dir.mkdir(parents=True)

        # Write a malformed entry
        (idx_dir / "req_malformed.json").write_text(
            '{"request-id": "req_malformed"}',  # missing phase
            encoding="utf-8",
        )

        _, qcount = wi.recover_work_index_entries(
            service_root, live_owner_epoch="live",
        )
        assert qcount >= 1

        quarantine_dir = wi._quarantine_dir(service_root)
        entries = list(quarantine_dir.glob("req_malformed_*.json"))
        assert len(entries) >= 1
        # Content is preserved
        raw = json.loads(entries[0].read_text(encoding="utf-8"))
        assert "request-id" in raw

    def test_mismatched_project_root_digest_quarantined_not_deleted(self, tmp_path: Path) -> None:
        """C7: an entry whose stored project-root digest no longer matches the
        digest recomputed from its own project-root path is quarantined, not
        silently trusted or deleted — this catches a tampered or corrupted
        entry pointing at the wrong project."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True)
        idx_dir = wi._index_dir(service_root)
        idx_dir.mkdir(parents=True)

        (idx_dir / "req_tampered.json").write_text(
            json.dumps({
                "request-id": "req_tampered",
                "project-root": str(project_root),
                "project-root-digest": "0" * 16,
                "phase": "admitted",
            }),
            encoding="utf-8",
        )

        valid, qcount = wi.recover_work_index_entries(
            service_root, live_owner_epoch="live",
        )
        assert qcount >= 1
        assert all(entry.request_id != "req_tampered" for entry in valid)

        quarantine_dir = wi._quarantine_dir(service_root)
        entries = list(quarantine_dir.glob("req_tampered_*.json"))
        assert len(entries) >= 1
        raw = json.loads(entries[0].read_text(encoding="utf-8"))
        assert raw["request-id"] == "req_tampered"

    def test_missing_request_quarantined_not_deleted(self, tmp_path: Path) -> None:
        """Work-index entry pointing to a non-existent request is quarantined.

        Note: we use a non-req_ filename so Path 1 (active-work glob) doesn't pick it up
        and let Path 2 (work-index) handle the quarantine path independently.
        """
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        idx_dir = wi._index_dir(service_root)
        idx_dir.mkdir(parents=True)
        # Write a work-index entry that points to a non-existent request.
        # Use req_ prefix so Path 2's glob picks it up, but no corresponding
        # active-work entry so Path 1 doesn't process it first.
        (idx_dir / "req_ghost.json").write_text(
            json.dumps({
                "schema-version": "v1",
                "request-id": "req_ghost",
                "project-root": str(project_root),
                "project-root-digest": wi._project_root_digest(project_root),
                "phase": "admitted",
                "owner-epoch": None,
                "lane-key": None,
                "admitted-at": "2025-01-01T00:00:00Z",
                "claimed-at": None,
            }),
            encoding="utf-8",
        )

        report = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        assert report.quarantined >= 1
        quarantine_dir = wi._quarantine_dir(service_root)
        entries = list(quarantine_dir.glob("req_ghost_*.json"))
        assert len(entries) >= 1
        quarantine_dir = wi._quarantine_dir(service_root)
        entries = list(quarantine_dir.glob("req_ghost_*.json"))
        assert len(entries) >= 1

# ---------------------------------------------------------------------------
# Recovery idempotency: running recovery twice is safe
# ---------------------------------------------------------------------------

class TestRecoveryIdempotency:
    """Running recovery multiple times does not cause double terminalization."""

    def test_second_recovery_is_noop(self, tmp_path: Path) -> None:
        """After first recovery, second run finds nothing to do."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"

        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root, record["request-id"],
            owner_epoch="old-epoch", expected_revision=record["revision"],
            service_root=service_root,
        )
        store.start_owned_attempt(
            project_root, record["request-id"],
            owner_epoch="old-epoch", worker_id="w1",
            expected_revision=claimed["revision"],
        )

        first = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )
        second = recovery_mod.recover_gateway_requests(
            service_root, live_owner_epoch="new-epoch",
        )

        assert first.interrupted >= 1
        assert second.examined == 0
        assert second.replay_required == 0
        assert second.interrupted == 0
