"""Detached process launch and non-PID ownership evidence for managed services."""
from __future__ import annotations

import hashlib
import logging
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.system.managed_service_contracts import ProcessEvidence
from audiagentic.foundation.system.process import kill_process_tree, pid_alive

process_error = make_error_factory("CON", "MPROC", "managed-process")
validation_error = make_error_factory("VAL", "MPROC", "managed-process")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessIdentity:
    """Live OS facts used to compare a process with durable evidence."""

    pid: int
    creation_identity: str | None = None
    command_fingerprint: str | None = None
    group_identity: str | None = None


@dataclass(frozen=True)
class DetachedLaunch:
    """Narrow declaration for a service process that may outlive its starter."""

    command: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    detached: bool = True

    def __post_init__(self) -> None:
        if not self.command or any(not isinstance(part, str) or not part for part in self.command):
            raise validation_error(1, "managed-process command must contain non-empty strings")
        if self.cwd is not None and not self.cwd.is_dir():
            raise validation_error(2, "managed-process working directory does not exist", cwd=str(self.cwd))


def command_fingerprint(command: Sequence[str]) -> str:
    """Hash argv without persisting potentially secret-bearing raw arguments."""
    digest = hashlib.sha256()
    for part in command:
        digest.update(part.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def process_creation_identity(pid: int) -> str | None:
    """Return a stable OS process creation identity when the platform exposes one."""
    if not pid_alive(pid):
        return None
    if os.name == "nt":
        return _windows_creation_identity(pid)
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        fields = proc_stat.read_text(encoding="utf-8").split()
        return f"proc-start:{fields[21]}"
    except (OSError, IndexError):
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        value = result.stdout.strip()
        return f"ps-start:{value}" if value else None


def _windows_creation_identity(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"filetime:{ticks}"
    finally:
        kernel32.CloseHandle(handle)


def observe_process(evidence: ProcessEvidence) -> ProcessIdentity | None:
    """Capture every live identity fact the platform exposes for comparison.

    ``ownership_matches`` compares three proofs; each one populated here is a
    real comparison instead of dead code (RV681 found only creation identity
    was ever observed). Facts that cannot be read stay None — conservative.
    """
    if not pid_alive(evidence.pid):
        return None
    group_identity: str | None = None
    fingerprint: str | None = None
    if os.name != "nt":
        try:
            group_identity = f"session:{os.getsid(evidence.pid)}"
        except OSError:
            pass
        try:
            raw = Path(f"/proc/{evidence.pid}/cmdline").read_bytes()
            parts = [
                part.decode("utf-8", errors="surrogateescape")
                for part in raw.split(b"\0")
                if part
            ]
            if parts:
                fingerprint = command_fingerprint(parts)
        except OSError:
            pass
    return ProcessIdentity(
        pid=evidence.pid,
        creation_identity=process_creation_identity(evidence.pid),
        command_fingerprint=fingerprint,
        group_identity=group_identity,
    )


def ownership_matches(evidence: ProcessEvidence, observed: ProcessIdentity | None) -> bool:
    """Require PID plus at least one matching non-PID ownership proof."""
    if observed is None or evidence.pid != observed.pid:
        return False
    comparisons = (
        (evidence.creation_identity, observed.creation_identity),
        (evidence.command_fingerprint, observed.command_fingerprint),
        (evidence.group_identity, observed.group_identity),
    )
    return any(expected is not None and expected == actual for expected, actual in comparisons)


def launch_detached(declaration: DetachedLaunch, *, owner_epoch: str) -> ProcessEvidence:
    """Launch one service process and return durable, credential-free evidence."""
    env = os.environ.copy()
    if declaration.env is not None:
        env.update(declaration.env)
    env["AUDIAGENTIC_SERVICE_OWNER_EPOCH"] = owner_epoch
    creationflags = 0
    start_new_session = False
    if declaration.detached:
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            creationflags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        else:
            start_new_session = True
    degraded_job_lifetime = False
    try:
        process = subprocess.Popen(
            declaration.command,
            cwd=declaration.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
            close_fds=True,
        )
    except OSError as exc:
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        if os.name != "nt" or not declaration.detached or not breakaway:
            raise process_error(
                3, "managed-process launch failed", executable=declaration.command[0]
            ) from exc
        try:
            process = subprocess.Popen(
                declaration.command,
                cwd=declaration.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags & ~breakaway,
                start_new_session=False,
                close_fds=True,
            )
        except OSError as fallback_exc:
            raise process_error(
                3, "managed-process launch failed", executable=declaration.command[0]
            ) from fallback_exc
        degraded_job_lifetime = True
        logger.warning(
            "managed process launched without Windows job breakaway",
            extra={"lifetime_scope": "session-child"},
        )
    creation_identity = process_creation_identity(process.pid)
    if creation_identity is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise process_error(4, "managed-process creation identity is unavailable", pid=process.pid)
    threading.Thread(
        target=process.wait,
        name=f"managed-process-reaper-{process.pid}",
        daemon=True,
    ).start()
    return ProcessEvidence(
        pid=process.pid,
        scope=(
            "shared-service-host"
            if declaration.detached and not degraded_job_lifetime
            else "session-child"
        ),
        command_fingerprint=command_fingerprint(declaration.command),
        ownership_proof_kind="creation-identity",
        owner_epoch=owner_epoch,
        creation_identity=creation_identity,
        group_identity=f"session:{process.pid}" if declaration.detached and os.name != "nt" else None,
    )


def current_process_evidence(
    *, owner_epoch: str, scope: str = "external-adopted"
) -> ProcessEvidence:
    """Build ownership evidence for an explicitly started current process."""
    pid = os.getpid()
    creation_identity = process_creation_identity(pid)
    if creation_identity is None:
        raise process_error(4, "managed-process creation identity is unavailable", pid=pid)
    group_identity = None
    if os.name != "nt":
        try:
            group_identity = f"session:{os.getsid(pid)}"
        except OSError:
            pass
    return ProcessEvidence(
        pid=pid,
        scope=scope,
        command_fingerprint=command_fingerprint(tuple(sys.argv)),
        ownership_proof_kind="creation-identity",
        owner_epoch=owner_epoch,
        creation_identity=creation_identity,
        group_identity=group_identity,
    )


def signal_owned_process(
    evidence: ProcessEvidence,
    observed: ProcessIdentity | None,
    *,
    force: bool,
) -> None:
    """Signal a process only after its durable non-PID proof still matches."""
    if not ownership_matches(evidence, observed):
        raise process_error(5, "managed-process ownership proof does not match", pid=evidence.pid)
    if force:
        kill_process_tree(evidence.pid)
        return
    try:
        os.kill(evidence.pid, signal.SIGTERM)
    except OSError:
        pass


__all__ = [
    "DetachedLaunch",
    "ProcessIdentity",
    "command_fingerprint",
    "current_process_evidence",
    "launch_detached",
    "observe_process",
    "ownership_matches",
    "process_creation_identity",
    "signal_owned_process",
]
