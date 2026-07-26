"""Unit tests for AS17 adopted-process contract (adopt/observe/stop).

Tests the formal adopt/observe/stop contract that foundation exposes for
already-spawned interactive children. The SDK (ACP) owns process creation;
foundation owns OS lifetime evidence and safe tree supervision.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from audiagentic.foundation.system.adopted_process import (
    AdoptedChild,
    AdoptionRefusal,
    OwnershipCheckResult,
    adopt_child,
    close_kill_job,
    observe_child,
    stop_child,
)
from audiagentic.foundation.system.managed_service_contracts import ProcessEvidence

# ── adopt_child tests ─────────────────────────────────────────────


class TestAdoptChild:
    """Test the adopt_child entry point."""

    def test_adopt_returns_refusal_when_pid_dead(self) -> None:
        """adopt_child returns AdoptionRefusal when the target PID is dead."""
        with patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=False):
            result = adopt_child(pid=9999, command=("agent",), owner_epoch="ep-1")

        assert isinstance(result, AdoptionRefusal)
        assert result.pid == 9999
        assert result.reason == "process-dead"

    def test_adopt_returns_refusal_when_creation_identity_unavailable(self) -> None:
        """adopt_child returns AdoptionRefusal when creation identity is None."""
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.process_creation_identity",
                return_value=None,
            ),
        ):
            result = adopt_child(pid=1234, command=("agent",), owner_epoch="ep-1")

        assert isinstance(result, AdoptionRefusal)
        assert result.reason == "creation-identity-none"

    def test_adopt_returns_refusal_on_creation_identity_exception(self) -> None:
        """adopt_child returns AdoptionRefusal when creation identity raises."""
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.process_creation_identity",
                side_effect=RuntimeError("no /proc"),
            ),
        ):
            result = adopt_child(pid=1234, command=("agent",), owner_epoch="ep-1")

        assert isinstance(result, AdoptionRefusal)
        assert result.reason == "creation-identity-unavailable"

    def test_adopt_succeeds_with_evidence_and_no_job_on_posix(self) -> None:
        """On POSIX, adopt_child captures evidence but no Job Object."""
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.process_creation_identity",
                return_value="proc-start:42",
            ),
            patch.object(os, "name", "posix"),
            patch("audiagentic.foundation.system.adopted_process._HAS_SESSION_ID", True),
            patch("audiagentic.foundation.system.adopted_process._getsid", return_value=5),
        ):
            result = adopt_child(
                pid=1234, command=("agent", "--model", "gpt-4"), owner_epoch="ep-1"
            )

        assert isinstance(result, AdoptedChild)
        assert result.evidence.pid == 1234
        assert result.evidence.scope == "session-child"
        assert result.evidence.owner_epoch == "ep-1"
        assert result.evidence.creation_identity == "proc-start:42"
        # Command fingerprint should NOT contain raw arguments.
        assert "--model" not in result.evidence.command_fingerprint
        assert "gpt-4" not in result.evidence.command_fingerprint
        assert result.kill_job_handle is None  # POSIX has no Job Object

    def test_adopt_is_external_flag_preserved(self) -> None:
        """The is_external flag survives adoption."""
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.process_creation_identity",
                return_value="filetime:123456",
            ),
            patch.object(os, "name", "posix"),
        ):
            result = adopt_child(
                pid=1234,
                command=("agent",),
                owner_epoch="ep-1",
                scope="session-child",
                is_external=True,
            )

        assert isinstance(result, AdoptedChild)
        assert result.is_external is True

    def test_adopt_external_on_windows_skips_job_object(self) -> None:
        """External adoption on Windows must never call adopt_pid_into_kill_job."""
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.process_creation_identity",
                return_value="filetime:123456",
            ),
            patch.object(os, "name", "nt"),
            patch(
                "audiagentic.foundation.system.supervised_process.adopt_pid_into_kill_job"
            ) as mock_adopt,
        ):
            result = adopt_child(
                pid=1234,
                command=("agent",),
                owner_epoch="ep-1",
                is_external=True,
            )

        assert isinstance(result, AdoptedChild)
        assert result.is_external is True
        assert result.kill_job_handle is None
        mock_adopt.assert_not_called()


# ── observe_child tests ───────────────────────────────────────────


class TestObserveChild:
    """Test the observe_child ownership verification."""

    def test_observe_returns_not_owned_when_pid_dead(self) -> None:
        """observe_child returns owned=False when PID is dead."""
        evidence = ProcessEvidence(
            pid=9999,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        with patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=False):
            result = observe_child(evidence)

        assert not result.owned
        assert not result.alive
        assert result.refusal_reason == "process-dead"

    def test_observe_returns_not_owned_when_ownership_mismatch(self) -> None:
        """PID-reused process fails ownership check."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:expected",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.observe_process",
                return_value=MagicMock(
                    pid=1234,
                    creation_identity="proc-start:999",  # different!
                    command_fingerprint=None,
                    group_identity=None,
                ),
            ),
            patch(
                "audiagentic.foundation.system.adopted_process.ownership_matches",
                return_value=False,
            ),
        ):
            result = observe_child(evidence)

        assert not result.owned
        assert result.alive  # PID is alive but identity changed
        assert result.refusal_reason == "ownership-mismatch"

    def test_observe_returns_owned_when_proof_matches(self) -> None:
        """Ownership holds when creation identity matches."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        with (
            patch("audiagentic.foundation.system.adopted_process.pid_alive", return_value=True),
            patch(
                "audiagentic.foundation.system.adopted_process.observe_process",
                return_value=MagicMock(pid=1234),
            ),
            patch(
                "audiagentic.foundation.system.adopted_process.ownership_matches",
                return_value=True,
            ),
        ):
            result = observe_child(evidence)

        assert result.owned
        assert result.alive
        assert result.refusal_reason is None


# ── stop_child tests ─────────────────────────────────────────────


class TestStopChild:
    """Test the stop_child safe-termination contract."""

    def test_stop_refuses_external_process(self) -> None:
        """External processes are never signalled (diagnostics-only)."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        adopted = AdoptedChild(evidence=evidence, is_external=True)

        result = stop_child(adopted)

        assert not result.stopped
        assert result.refusal_reason == "external-process"

    def test_stop_refuses_pid_reuse(self) -> None:
        """PID-reused process is refused — never signal a new occupant."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        adopted = AdoptedChild(evidence=evidence, is_external=False)

        with patch(
            "audiagentic.foundation.system.adopted_process.observe_child",
            return_value=OwnershipCheckResult(
                owned=False, alive=True, observed=None, refusal_reason="ownership-mismatch"
            ),
        ):
            result = stop_child(adopted)

        assert not result.stopped
        assert result.refusal_reason == "ownership-mismatch"

    def test_stop_refuses_dead_process(self) -> None:
        """Dead process is refused — nothing to stop."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        adopted = AdoptedChild(evidence=evidence, is_external=False)

        with patch(
            "audiagentic.foundation.system.adopted_process.observe_child",
            return_value=OwnershipCheckResult(
                owned=False, alive=False, observed=None, refusal_reason="process-dead"
            ),
        ):
            result = stop_child(adopted)

        assert not result.stopped
        assert result.refusal_reason == "process-dead"

    def test_stop_succeeds_when_owned(self) -> None:
        """Owned alive process is killed."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        adopted = AdoptedChild(evidence=evidence, is_external=False)

        with (
            patch(
                "audiagentic.foundation.system.adopted_process.observe_child",
                return_value=OwnershipCheckResult(owned=True, alive=True, observed=MagicMock()),
            ),
            patch("audiagentic.foundation.system.adopted_process.kill_process_tree") as mock_kill,
        ):
            result = stop_child(adopted)

        assert result.stopped
        mock_kill.assert_called_once_with(1234)


# ── close_kill_job tests ─────────────────────────────────────────


class TestCloseKillJob:
    """Test the close_kill_job teardown helper."""

    def test_close_kill_job_noop_when_none(self) -> None:
        """No exception when kill_job_handle is None (POSIX)."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        adopted = AdoptedChild(evidence=evidence, kill_job_handle=None)

        # Should not raise
        close_kill_job(adopted)

    def test_close_kill_job_calls_handler(self) -> None:
        """Kill Job Object handle is closed."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        fake_handle = object()
        adopted = AdoptedChild(evidence=evidence, kill_job_handle=fake_handle)

        with patch("audiagentic.foundation.system.adopted_process._close_job_handle") as mock_close:
            close_kill_job(adopted)

        mock_close.assert_called_once_with(fake_handle)

    def test_close_kill_job_noop_external(self) -> None:
        """External children: close_kill_job no-ops even if a handle is supplied."""
        evidence = ProcessEvidence(
            pid=1234,
            scope="session-child",
            command_fingerprint="sha256:abc",
            ownership_proof_kind="creation-identity",
            owner_epoch="ep-1",
            creation_identity="proc-start:42",
        )
        fake_handle = object()
        adopted = AdoptedChild(evidence=evidence, kill_job_handle=fake_handle, is_external=True)

        with patch("audiagentic.foundation.system.adopted_process._close_job_handle") as mock_close:
            close_kill_job(adopted)

        mock_close.assert_not_called()


# ── supervised_process Job Object handle-leak tests ───────────

from audiagentic.foundation.system.supervised_process import (
    _assign_handle_to_kill_job,
)


class TestJobObjectHandleLeak:
    """Test that the Job Object handle is not leaked on SetInformationJobObject failure."""

    def test_setinfo_failure_closes_job_handle(self) -> None:
        """When SetInformationJobObject fails, the job handle must be closed."""
        import platform

        import pytest

        if platform.system() != "Windows":
            pytest.skip("Windows-only: requires ctypes.WinDLL")
        """When SetInformationJobObject fails, the job handle must be closed."""
        from unittest.mock import MagicMock, patch

        mock_kernel32 = MagicMock()
        # CreateJobObject succeeds with a valid handle
        mock_kernel32.CreateJobObjectW.return_value = 42
        # SetInformationJobObject fails
        mock_kernel32.SetInformationJobObject.return_value = False

        # Patch ctypes.WinDLL so it returns our mock kernel32
        import ctypes

        with patch.object(ctypes, "WinDLL", return_value=mock_kernel32):
            result = _assign_handle_to_kill_job(100)

        assert result is None
        # CloseHandle must be called exactly once: for the leaked job handle
        mock_kernel32.CloseHandle.assert_called_once_with(42)
