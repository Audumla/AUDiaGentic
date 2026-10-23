"""Reusable OS-backed file fence for high-frequency journal appends.

Unlike a startup claim, this fence does not create/unlink a PID file for
every append. The OS releases its advisory lock on close or process death.
The containing resource must not be purged while an owner is still active.
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

from .process import _claim_thread_lock, _process_error, _release_thread_lock


class AdvisoryLock:
    def __init__(self, path: Path, *, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout
        self._stream = None
        self._thread_lock = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        self._thread_lock = _claim_thread_lock(self.path)
        if not self._thread_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            _release_thread_lock(self.path, self._thread_lock, acquired=False)
            self._thread_lock = None
            raise self._timeout_error()
        try:
            try:
                self._stream = self.path.open("a+b", buffering=0)
            except FileNotFoundError:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = self.path.open("a+b", buffering=0)
            if os.fstat(self._stream.fileno()).st_size == 0:
                self._stream.write(b"\0")
            while True:
                try:
                    self._stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise self._timeout_error() from exc
                    time.sleep(min(0.01, remaining))
        except BaseException:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            _release_thread_lock(self.path, self._thread_lock)
            self._thread_lock = None
            raise

    def _timeout_error(self):
        return _process_error(
            "TO",
            2,
            "Timed out waiting for journal file lock",
            path=str(self.path),
            timeout=self.timeout,
        )

    def __exit__(self, *_):
        try:
            if self._stream is not None:
                try:
                    self._stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
                finally:
                    self._stream.close()
                    self._stream = None
        finally:
            if self._thread_lock is not None:
                _release_thread_lock(self.path, self._thread_lock)
                self._thread_lock = None
