"""Run a host subprocess so its entire descendant tree dies with the launcher.

Harness host processes (the pi node CLI, opencode) spawn stdio MCP/LSP servers
as grandchildren. Without OS-enforced cleanup those orphan and accumulate when
the python launcher exits abnormally (crash, kill, terminal close) — the exact
leak that leaves stale ``audiagentic mcp`` and ``yaml-language-server`` processes
running for days.

``supervised_run`` closes that gap on both platforms:

- Windows: the host is assigned to a Job Object created with
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. The kernel terminates every process in
  the job when the last handle to it closes — which happens automatically when
  the launcher process dies, *even on crash or external TerminateProcess*. This
  is the only teardown that survives a hard-killed parent, because no python
  ``finally`` runs in that case.
- POSIX: a recursive ``kill_process_tree`` in ``finally`` reaps the host and all
  descendants. The host stays in the launcher's process group so interactive
  TUIs keep terminal focus and receive Ctrl+C naturally.

On both platforms a belt-and-suspenders ``kill_process_tree`` runs in ``finally``
and SIGINT/SIGTERM received by the launcher are forwarded to the host.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from audiagentic.foundation.system.process import kill_process_tree

logger = logging.getLogger(__name__)

# --- Windows Job Object plumbing ------------------------------------------

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9


def _assign_to_kill_job(proc: subprocess.Popen) -> object | None:
    """Assign *proc* to a kill-on-close Job Object; return the job handle.

    The returned handle MUST stay referenced for the host's lifetime — when it
    is closed (explicitly, or by the OS when the launcher dies) the kernel kills
    every process in the job. Returns None if the OS refuses (older Windows /
    already in a non-nestable job); the ``finally`` tree-kill remains as backup.
    """
    return _assign_handle_to_kill_job(int(proc._handle))  # type: ignore[attr-defined]


def adopt_pid_into_kill_job(pid: int) -> object | None:
    """Adopt an already-spawned child (by pid) into a kill-on-close Job Object.

    For children spawned by third-party code (e.g. the ACP SDK) where no
    ``Popen`` handle is available. Same contract as ``_assign_to_kill_job``:
    keep the returned handle referenced for the child's lifetime; closing it —
    including implicitly when this process dies — kills the child's tree.
    Returns None off-Windows or when the OS refuses.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    process_set_quota = 0x0100
    process_terminate = 0x0001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = kernel32.OpenProcess(process_set_quota | process_terminate, False, pid)
    if not handle:
        logger.debug("OpenProcess for job adoption failed (err=%s)", ctypes.get_last_error())
        return None
    try:
        return _assign_handle_to_kill_job(int(handle))
    finally:
        kernel32.CloseHandle(handle)


def _assign_handle_to_kill_job(process_handle: int) -> object | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.debug("CreateJobObjectW failed (err=%s)", ctypes.get_last_error())
        return None

    info = _EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    ):
        logger.debug("SetInformationJobObject failed (err=%s)", ctypes.get_last_error())
        return None

    if not kernel32.AssignProcessToJobObject(job, process_handle):
        # ERROR_ACCESS_DENIED here means the host is already in a job that
        # disallows nesting. Rare on Windows 8+; fall back to finally tree-kill.
        logger.debug("AssignProcessToJobObject failed (err=%s)", ctypes.get_last_error())
        kernel32.CloseHandle(job)
        return None

    return job


# --- Public API -----------------------------------------------------------


def _close_job_handle(job: object | None) -> None:
    if job is None or os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(job)
    except Exception:  # noqa: BLE001 - teardown must remain best effort
        logger.warning("Failed to close process Job Object", exc_info=True)


@dataclass
class SupervisedProcess:
    """Owned child process whose descendant tree is reaped on close.

    The handle is deliberately small: callers retain normal ``Popen`` pipe
    access while lifecycle ownership remains explicit and reusable by both
    blocking harness launches and short-lived isolated workers.
    """

    process: subprocess.Popen[str]
    _job: object | None = None
    _process_group_id: int | None = None
    _closed: bool = False

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def stdin(self) -> IO[str] | None:
        return self.process.stdin

    @property
    def stdout(self) -> IO[str] | None:
        return self.process.stdout

    @property
    def stderr(self) -> IO[str] | None:
        return self.process.stderr

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def communicate(
        self,
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        stdout, stderr = self.process.communicate(input=input, timeout=timeout)
        return stdout or "", stderr or ""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process_group_id is not None and os.name != "nt":
                try:
                    os.killpg(self._process_group_id, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            kill_process_tree(self.process.pid)
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.warning("Supervised process did not exit after tree teardown")
        finally:
            _close_job_handle(self._job)
            self._job = None

    def __enter__(self) -> SupervisedProcess:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def spawn_supervised(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    isolated_process_group: bool = False,
) -> SupervisedProcess:
    """Start an owned child with optional replacement environment and pipes."""
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        text=True,
        encoding="utf-8",
        start_new_session=isolated_process_group and os.name != "nt",
    )
    job: object | None = None
    if os.name == "nt":
        try:
            job = _assign_to_kill_job(proc)
        except Exception:  # noqa: BLE001 — never leave an unsupervised child
            logger.warning("Job Object assignment failed; relying on explicit teardown", exc_info=True)
    return SupervisedProcess(
        process=proc,
        _job=job,
        _process_group_id=(proc.pid if isolated_process_group and os.name != "nt" else None),
    )


def supervised_run(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run *command* to completion, guaranteeing its child tree is reaped.

    Drop-in replacement for ``subprocess.run(command, cwd=cwd, env=env).returncode``
    that additionally tears down the whole descendant tree on normal exit,
    exception, or launcher signal — and, on Windows, even if the launcher is
    hard-killed (via the Job Object).
    """
    owned = spawn_supervised(command, cwd=cwd, env=env)
    proc = owned.process

    previous: dict[int, object] = {}

    def _forward(signum: int, _frame: object) -> None:
        try:
            proc.send_signal(signum)
        except (OSError, ValueError):
            pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _forward)
        except (OSError, ValueError):
            pass  # not on the main thread, or signal unsupported on platform

    try:
        return proc.wait()
    finally:
        owned.close()
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)  # type: ignore[arg-type]
            except (OSError, ValueError):
                pass
