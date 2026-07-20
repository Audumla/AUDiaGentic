"""Formal adopt/observe/stop contract for already-spawned interactive children.

AS17 foundation seam: the SDK (ACP, LSP) owns process creation and protocol
lifecycle; foundation owns OS lifetime evidence and safe tree supervision.

This module provides a narrow three-phase contract:

1. **adopt** — establish durable ownership evidence for an already-spawned
   child that another layer (e.g. ACP SDK) created. Captures ProcessEvidence
   plus platform-specific hard-death hooks (Windows Job Object).

2. **observe** — re-read live OS identity facts and compare against the
   adopted evidence to verify continued ownership. Detects PID reuse.

3. **stop** — terminate the child tree only if ownership proof still matches.
   Refuses to signal a PID-reused process. Respects owned-vs-external:
   externally-adopted processes are never signalled by the adopter; they
   are tracked for diagnostics and orphan reconciliation only.

Design principles (AS17):
- No global registry or ManagedService record — this is a per-child evidence
  token, not a system-wide service store.
- ACP retains connection/protocol lifecycle ownership; foundation provides
  OS lifetime evidence and safe termination as a seam.
- Cross-platform hard-death guarantees are honest: Windows Job Object
  survives hard gateway kill; POSIX cleanup is graceful/exception only.

POSIX hard-parent-death honesty (RV720):
An in-process adopter CANNOT guarantee child-tree death after the gateway
is SIGKILLed on POSIX. Process groups and atexit do not provide it. This
module explicitly does NOT claim immediate descendant death on POSIX hard
gateway kill — the guarantee is graceful/exception cleanup plus identity-safe
next-start orphan reconciliation (AS26). On Windows, the Job Object provides
the stronger guarantee.

Usage pattern:
    adopted = adopt_child(pid=1234, command=("agent",), owner_epoch="ep-1")
    # later: verify ownership still holds before any action
    observed = observe_child(adopted.evidence)
    if ownership_matches(adopted.evidence, observed):
        stop_child(adopted)  # safe — identity proof matches
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

# Platform capability: session ID query (POSIX only).  Evaluated once at
# import time so tests can mock the guard without mutating os.name.
_getsid = getattr(os, "getsid", None)
_HAS_SESSION_ID = callable(_getsid)

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.system.managed_process import (
    ProcessEvidence,
    observe_process,
    ownership_matches,
    process_creation_identity,
)
from audiagentic.foundation.system.process import kill_process_tree, pid_alive
from audiagentic.foundation.system.supervised_process import _close_job_handle

adopt_error = make_error_factory("ERR", "ADPT", "adopted-process")
validation_error = make_error_factory("VAL", "ADPT", "adopted-process")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdoptionRefusal:
    """Describes why adopt_child refused to establish ownership.

    adoption_refused is returned instead of raising when the child exists
    but cannot be adopted (e.g. already in a non-nestable Windows Job,
    creation identity unavailable). The caller may still use the child
    without foundation supervision — the SDK's own teardown remains.
    """

    pid: int
    reason: str
    detail: dict[str, object] | None = None


@dataclass(frozen=True)
class OwnershipCheckResult:
    """Describes the result of an ownership verification (observe + compare).

    Attributes
    ----------
    owned : bool
        True if PID plus non-PID proof still match; False means the process
        is either dead, PID-reused, or externally owned.
    alive : bool
        True if the process is still alive (pid_alive).
    observed : ProcessIdentity | None
        Live OS identity facts, or None if the process is gone.
    refusal_reason : str | None
        Why ownership was denied when ``owned`` is False.
    """

    owned: bool
    alive: bool
    observed: object | None  # ProcessIdentity from managed_process
    refusal_reason: str | None = None


@dataclass(frozen=True)
class StopResult:
    """Describes the result of a stop_child attempt.

    Attributes
    ----------
    stopped : bool
        True if the process tree was terminated.
    refusal_reason : str | None
        Why stop refused when ``stopped`` is False.
    """

    stopped: bool
    refusal_reason: str | None = None


@dataclass
class AdoptedChild:
    """Owned child whose OS lifetime evidence is captured by foundation.

    This is the narrow contract token for an already-spawned child that
    another layer (e.g. ACP SDK) created. The adopter retains protocol
    lifecycle ownership; foundation owns OS evidence and safe termination.

    ``evidence`` holds the durable ProcessEvidence captured at adoption time.
    ``kill_job_handle`` is a Windows-only Job Object handle for hard-death
    guarantee — closing it (explicitly or on process death) kills the child
    tree. On POSIX this is always None.

    ``is_external`` marks externally-adopted processes that the adopter
    must NOT signal — they are tracked for diagnostics and orphan
    reconciliation only (e.g. processes started before our gateway took over).

    Parameters
    ----------
    evidence : ProcessEvidence
        Durable ownership facts captured at adoption time.
    kill_job_handle : object | None
        Windows Job Object handle (None on POSIX or when refused).
    is_external : bool
        True if this process was not spawned by the current gateway and
        should never be signalled by it.
    """

    evidence: ProcessEvidence
    kill_job_handle: object | None = None
    is_external: bool = False


def _windows_creation_identity(pid: int) -> str | None:
    """Read creation identity via Windows process times."""
    from audiagentic.foundation.system.managed_process import (
        _windows_creation_identity as _win_ci,
    )
    return _win_ci(pid)


def adopt_child(
    *,
    pid: int,
    command: tuple[str, ...],
    owner_epoch: str,
    scope: str = "session-child",
    is_external: bool = False,
) -> AdoptedChild | AdoptionRefusal:
    """Establish foundation ownership evidence for an already-spawned child.

    Captures ProcessEvidence (creation identity, command fingerprint, group
    identity) and — on Windows — adopts the child into a kill-on-close Job
    Object so hard-killing the gateway does not orphan its tree.

    Returns AdoptedChild on success, AdoptionRefusal if evidence cannot be
    captured (e.g. creation identity unavailable). The caller may still use
    the child without foundation supervision.

    Parameters
    ----------
    pid : int
        OS PID of the already-spawned child.
    command : tuple[str, ...]
        The command the child was started with (for fingerprinting).
    owner_epoch : str
        Epoch identifier of the owner that adopted this child.
    scope : str
        Process scope label; "session-child" for ACP agent children,
        "shared-service-host" for managed services.
    is_external : bool
        True if the process was not spawned by the current gateway and
        should never be signalled by it (diagnostics-only adoption).
    """
    from audiagentic.foundation.system.managed_process import command_fingerprint

    # Verify the process is alive before investing in evidence capture.
    if not pid_alive(pid):
        return AdoptionRefusal(
            pid=pid,
            reason="process-dead",
            detail={"message": "target PID is not alive at adoption time"},
        )

    # Capture creation identity — required for ownership proof.
    try:
        creation_identity = process_creation_identity(pid)
    except Exception as exc:  # noqa: BLE001 — evidence capture is best effort
        logger.debug("failed to capture creation identity", exc_info=True)
        return AdoptionRefusal(
            pid=pid,
            reason="creation-identity-unavailable",
            detail={"message": str(exc)},
        )

    if creation_identity is None:
        return AdoptionRefusal(
            pid=pid,
            reason="creation-identity-none",
            detail={"message": "platform does not expose creation identity"},
        )

    # Build durable evidence.
    group_identity: str | None = None
    if _HAS_SESSION_ID:
        try:
            group_identity = f"session:{_getsid(pid)}"
        except OSError:
            pass

    evidence = ProcessEvidence(
        pid=pid,
        scope=scope,
        command_fingerprint=command_fingerprint(command),
        ownership_proof_kind="creation-identity",
        owner_epoch=owner_epoch,
        creation_identity=creation_identity,
        group_identity=group_identity,
    )

    # Windows: adopt into kill-on-close Job Object for hard-death guarantee.
    # External children are diagnostics-only — no kill-job handle (they must
    # never be signalled by the adopter).
    kill_job_handle = None
    if os.name == "nt" and not is_external:
        from audiagentic.foundation.system.supervised_process import (
            adopt_pid_into_kill_job,
        )

        kill_job_handle = adopt_pid_into_kill_job(pid)

    return AdoptedChild(
        evidence=evidence,
        kill_job_handle=kill_job_handle,
        is_external=is_external,
    )


def observe_child(evidence: ProcessEvidence) -> OwnershipCheckResult:
    """Verify continued ownership by re-reading live OS identity facts.

    Returns OwnershipCheckResult with ``owned=True`` only if the PID is alive
    AND at least one non-PID proof still matches (creation identity, command
    fingerprint, or group identity). ``owned=False`` means the process is
    either dead, PID-reused, or externally owned.

    This is the gate for safe stop: never signal without ownership proof.
    """
    if not pid_alive(evidence.pid):
        return OwnershipCheckResult(
            owned=False,
            alive=False,
            observed=None,
            refusal_reason="process-dead",
        )

    observed = observe_process(evidence)
    if observed is None:
        return OwnershipCheckResult(
            owned=False,
            alive=True,  # pid_alive passed but observe failed
            observed=None,
            refusal_reason="unobservable",
        )

    if ownership_matches(evidence, observed):
        return OwnershipCheckResult(
            owned=True,
            alive=True,
            observed=observed,
        )

    # PID is alive but proofs don't match — PID reuse or identity change.
    return OwnershipCheckResult(
        owned=False,
        alive=True,
        observed=observed,
        refusal_reason="ownership-mismatch",
    )


def stop_child(adopted: AdoptedChild) -> StopResult:
    """Terminate the adopted child tree only if ownership still holds.

    Steps:
    1. Verify alive + ownership match (observe_child). If mismatch or dead,
       refuse — never signal a PID-reused process.
    2. If ``is_external``, refuse — external processes are diagnostics-only.
    3. Call kill_process_tree to terminate the child tree (SIGKILL on POSIX,
       taskkill /T /F on Windows).

    Returns StopResult describing the outcome.

    Parameters
    ----------
    adopted : AdoptedChild
        The adoption token with evidence and optional Job Object handle.
    """
    # External processes: never signal (diagnostics/orphan reconciliation only).
    if adopted.is_external:
        return StopResult(
            stopped=False,
            refusal_reason="external-process",
        )

    # Verify ownership still holds — refuse PID-reused targets.
    check = observe_child(adopted.evidence)
    if not check.owned:
        return StopResult(
            stopped=False,
            refusal_reason=check.refusal_reason or "ownership-mismatch",
        )

    # Ownership verified — safe to signal.
    try:
        kill_process_tree(adopted.evidence.pid)
    except Exception as exc:  # noqa: BLE001 — teardown must be best effort
        logger.warning("kill_process_tree failed", exc_info=True)
        return StopResult(stopped=False, refusal_reason=f"kill-failed:{exc}")

    return StopResult(stopped=True)


def close_kill_job(adopted: AdoptedChild) -> None:
    """Close the Windows Job Object handle for an adopted child.

    On Windows, closing the handle triggers JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    which kills every process in the job — including descendants of the
    originally-adopted child. This is the hard-death guarantee that survives
    even when the gateway itself is SIGKILLed (no atexit/finally runs).

    External children are never signalled — close_kill_job no-ops for them
    as defense in depth (even if a handle was somehow supplied).

    On POSIX this is a no-op (kill_job_handle is always None).
    Always safe to call — idempotent and exception-free.
    """
    if adopted.is_external:
        return
    if adopted.kill_job_handle is not None:
        _close_job_handle(adopted.kill_job_handle)


__all__ = [
    "AdoptedChild",
    "AdoptionRefusal",
    "OwnershipCheckResult",
    "StopResult",
    "adopt_child",
    "observe_child",
    "stop_child",
    "close_kill_job",
]
