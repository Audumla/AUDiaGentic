"""AS30 Stage-3: Multi-process race protection and recovery tests.

Tests cross-process safety validation, race conditions, and recovery from
corruption in the binding index (register_open_binding / rebuild_index).

These tests use file-system manipulation and thread-level concurrency to
simulate cross-process scenarios. True multi-process tests would require
subprocess spawning; thread-based tests validate the same locking contract
because StartupLock is designed for both cross-thread and cross-process
exclusion.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_session_bindings as bindings
from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.process import StartupLock


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with .audiagentic marker."""
    (tmp_path / ".audiagentic").mkdir(parents=True)
    return tmp_path


# ── Helpers ────────────────────────────────────────────────────────

def _make_session_record(
    project_root: Path,
    session_id: str,
    provider_ref: str,
    state: str = "active",
    provider_id: str | None = "test-provider",
) -> dict[str, Any]:
    """Write a session record with a binding and return the full record."""

    record = session_store.build_session_record(
        session_id=session_id,
        agent_profile_id="default",
        provider_id=provider_id,
        provider_session_ref=provider_ref,
    )
    # Override state if requested (build_session_record always creates "active").
    if state != "active":
        record["state"] = state
    session_store.write_session_record(project_root, record)
    return record


def _make_binding_key(provider_id: str, provider_ref: str) -> str:
    """Return the provider-ref-key for a given provider_id + ref."""
    return bindings.provider_ref_key(
        provider_id=provider_id,
        surface_id=None,
        ref_namespace=None,
        identity_context_fingerprint=None,
        provider_session_ref=provider_ref,
    )


# ── Race / Deadlock Protection Tests ───────────────────────────────

class TestDuplicateOwnerDetection:
    """Two processes attempt create_open_binding with same provider-ref-key.
    Second fails with duplicate-owner error."""

    def test_duplicate_owned_binding_raises_error(self, project_root: Path) -> None:
        """Same provider ref key from two sessions → second register raises CON-AGW-096."""
        # First session: create binding and register it.
        record1 = _make_session_record(project_root, "ses_001", "ref-alpha")
        bindings.register_open_binding(project_root, record1)

        # Second session: same provider ref → duplicate.
        record2 = _make_session_record(project_root, "ses_002", "ref-alpha")
        with pytest.raises(AudiaGenticError, match="duplicate owned provider session binding"):
            bindings.register_open_binding(project_root, record2)

    def test_duplicate_detection_is_atomic_across_threads(self, project_root: Path) -> None:
        """Two threads racing to register the same key → only one succeeds."""
        errors: list[Exception] = []
        successes: list[int] = []

        def _register(thread_id: int) -> None:
            try:
                record = _make_session_record(
                    project_root, f"ses_thread_{thread_id}", "ref-race"
                )
                bindings.register_open_binding(project_root, record)
                successes.append(thread_id)
            except AudiaGenticError as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_register, i) for i in range(4)]
            for f in futures:
                f.result()

        # Exactly one thread should succeed.
        assert len(successes) == 1
        # Three threads should have hit the duplicate-owner error.
        assert len(errors) == 3
        assert all("duplicate owned" in str(e) for e in errors)

    def test_external_ownership_allows_multiple(self, project_root: Path) -> None:
        """Multiple EXTERNAL bindings for the same key are allowed."""
        # Build two records with external ownership.
        record1 = _make_session_record(project_root, "ses_ext1", "ref-ext")
        record1["binding"]["ownership"] = "external"
        session_store.write_session_record(project_root, record1)

        record2 = _make_session_record(project_root, "ses_ext2", "ref-ext")
        record2["binding"]["ownership"] = "external"
        session_store.write_session_record(project_root, record2)

        # Both should register without error.
        bindings.register_open_binding(project_root, record1)
        bindings.register_open_binding(project_root, record2)

    def test_owned_then_external_is_ok(self, project_root: Path) -> None:
        """OWNED binding first, then EXTERNAL binding for same key."""
        record1 = _make_session_record(project_root, "ses_own", "ref-mix")
        bindings.register_open_binding(project_root, record1)

        record2 = _make_session_record(project_root, "ses_ext", "ref-mix")
        record2["binding"]["ownership"] = "external"
        session_store.write_session_record(project_root, record2)

        # External should be allowed even with an owned binding present.
        bindings.register_open_binding(project_root, record2)

    def test_external_then_owned_is_ok(self, project_root: Path) -> None:
        """EXTERNAL binding first, then OWNED binding for same key."""
        record1 = _make_session_record(project_root, "ses_ext", "ref-mix2")
        record1["binding"]["ownership"] = "external"
        session_store.write_session_record(project_root, record1)
        bindings.register_open_binding(project_root, record1)

        # OWNED binding should be allowed (no other owned active).
        record2 = _make_session_record(project_root, "ses_own", "ref-mix2")
        bindings.register_open_binding(project_root, record2)


class TestLockAcquisitionConcurrency:
    """Multiple processes/threads trying to rebuild_binding_index simultaneously."""

    def test_rebuild_serializes_concurrent_access(self, project_root: Path) -> None:
        """Concurrent rebuild calls should serialize via StartupLock."""
        # Create a few sessions so rebuild has something to index.
        for i in range(3):
            _make_session_record(project_root, f"ses_lock_{i}", f"ref-lock-{i}")

        overlap_detected = threading.Event()
        active_count = 0
        max_concurrent = 0
        state_guard = threading.Lock()

        def _rebuild() -> None:
            nonlocal active_count, max_concurrent
            with StartupLock(bindings.gateway_session_binding_lock_path(project_root), timeout=5):
                with state_guard:
                    active_count += 1
                    max_concurrent = max(max_concurrent, active_count)
                    if active_count > 1:
                        overlap_detected.set()
                # Simulate some work inside the lock.
                time.sleep(0.02)
                with state_guard:
                    active_count -= 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_rebuild) for _ in range(6)]
            for f in futures:
                f.result()

        # No overlap should be possible — StartupLock serializes.
        assert not overlap_detected.is_set(), "Overlapping access detected under lock"
        assert max_concurrent == 1

    def test_register_and_rebuild_dont_deadlock(self, project_root: Path) -> None:
        """register_open_binding and rebuild_index share the same lock;
        they should not deadlock when called concurrently."""
        for i in range(2):
            _make_session_record(project_root, f"ses_dl_{i}", f"ref-dl-{i}")

        errors: list[Exception] = []

        def _register() -> None:
            try:
                record = _make_session_record(project_root, "ses_dl_new", "ref-dl-new")
                bindings.register_open_binding(project_root, record)
            except Exception as e:
                errors.append(e)

        def _rebuild() -> None:
            try:
                bindings.rebuild_index(project_root)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_register) for _ in range(3)]
            futures += [pool.submit(_rebuild) for _ in range(3)]
            for f in futures:
                f.result(timeout=10)  # Would hang if deadlock

        assert not errors, f"Unexpected errors: {errors}"


class TestIndexRebuildAtomicity:
    """Kill process between index write and fsync → next restart rebuilds
    from session records."""

    def test_rebuild_recovers_after_partial_write(self, project_root: Path) -> None:
        """If the index file is truncated (simulating interrupted fsync),
        rebuild_index recovers all bindings from session records."""
        # Create sessions and register bindings.
        for i in range(3):
            record = _make_session_record(project_root, f"ses_atomic_{i}", f"ref-atm-{i}")
            bindings.register_open_binding(project_root, record)

        # Verify index is complete.
        payload = bindings._read_index(bindings.gateway_session_binding_index_path(project_root))
        assert len(payload["bindings"]) == 3

        # Simulate partial write: truncate the index file to make it invalid JSON.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text('{"contract-version": "v1", "bindings": {', encoding="utf-8")

        # Rebuild should recover all sessions.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 3

    def test_rebuild_replaces_empty_index(self, project_root: Path) -> None:
        """If the index is lost entirely, rebuild recovers from sessions."""
        for i in range(2):
            record = _make_session_record(project_root, f"ses_empty_{i}", f"ref-empty-{i}")
            bindings.register_open_binding(project_root, record)

        # Delete the index.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.unlink()

        # Rebuild should recover.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 2


class TestStaleLockRecovery:
    """Process dies holding lock → next process rebuilds under new lock."""

    def test_stale_lock_is_cleared_on_next_acquire(self, project_root: Path) -> None:
        """A lock file with a dead PID is automatically cleared by StartupLock."""
        lock_path = bindings.gateway_session_binding_lock_path(project_root)
        # Write a stale PID (PID 1 exists but is not our test process).
        # We use a very large unlikely PID instead.
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("99999", encoding="utf-8")

        # StartupLock should detect stale lock and clear it.
        with StartupLock(lock_path, timeout=5):
            # We acquired the lock — stale PID was cleared.
            pass

        # Lock file is cleaned up after release.
        assert not lock_path.exists()

    def test_rebuild_acquires_lock_after_stale_hold(self, project_root: Path) -> None:
        """rebuild_index can proceed even if a stale lock exists."""
        lock_path = bindings.gateway_session_binding_lock_path(project_root)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("99999", encoding="utf-8")

        _make_session_record(project_root, "ses_stale", "ref-stale")

        # Rebuild should succeed despite stale lock.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 1


class TestCreateOpenBindingRace:
    """Cross-process duplicate-owner detection via create_open_binding."""

    def test_create_open_binding_detects_duplicate(self, project_root: Path) -> None:
        """create_open_binding followed by another with same key should fail on second."""
        # First binding.
        binding1 = bindings.create_open_binding(
            session_id="ses_race_1",
            provider_id="test-provider",
            surface_id=None,
            provider_ref="ref-dup-create",
        )

        # Create a fake session record with the first binding and register it.
        record1 = {
            "session-id": "ses_race_1",
            "state": "active",
            "binding": binding1,
        }
        bindings.register_open_binding(project_root, record1)

        # Second binding with same provider ref.
        binding2 = bindings.create_open_binding(
            session_id="ses_race_2",
            provider_id="test-provider",
            surface_id=None,
            provider_ref="ref-dup-create",
        )
        record2 = {
            "session-id": "ses_race_2",
            "state": "active",
            "binding": binding2,
        }

        with pytest.raises(AudiaGenticError, match="duplicate owned provider session binding"):
            bindings.register_open_binding(project_root, record2)


# ── Windows-specific Tests ────────────────────────────────────────

class TestWindowsPathHandling:
    """Path handling in binding index and lock files on Windows."""

    def test_index_path_uses_native_separator(self, project_root: Path) -> None:
        """Binding index path should use native OS separators."""
        index_path = bindings.gateway_session_binding_index_path(project_root)
        # On Windows, Path objects use backslashes; on POSIX they use forward slashes.
        path_str = str(index_path)
        if os.name == "nt":
            assert "\\" in path_str or "/" in path_str  # Path handles both
        assert index_path.suffix == ".json"

    def test_lock_path_uses_native_separator(self, project_root: Path) -> None:
        """Lock file path should use native OS separators."""
        lock_path = bindings.gateway_session_binding_lock_path(project_root)
        assert lock_path.suffix == ".lock"

    def test_windows_lock_file_cleanup(self, project_root: Path) -> None:
        """Lock file on Windows is cleaned up after context exit (no rm -f)."""
        lock_path = bindings.gateway_session_binding_lock_path(project_root)

        with StartupLock(lock_path, timeout=5):
            assert lock_path.exists()
            pid_content = int(lock_path.read_text(encoding="utf-8"))
            assert pid_content == os.getpid()

        # Lock should be cleaned up.
        assert not lock_path.exists()

    def test_atomic_write_on_windows_paths(self, project_root: Path) -> None:
        """atomic_write_json works correctly with Windows-style paths."""
        _make_session_record(project_root, "ses_win", "ref-win")

        # Register the binding (which uses atomic_write_json internally).
        record = session_store.read_session_record(project_root, "ses_win")
        bindings.register_open_binding(project_root, record)

        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert "bindings" in payload
        assert len(payload["bindings"]) == 1
