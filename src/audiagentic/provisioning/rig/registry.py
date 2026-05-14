from __future__ import annotations

import json
import os
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal path helpers
# ---------------------------------------------------------------------------

def _rig_runtime_dir() -> Path:
    from audiagentic.provisioning.home import global_harness_runtime
    return global_harness_runtime() / "rig"


def _rig_json() -> Path:
    return _rig_runtime_dir() / "rig.json"


def _clients_dir() -> Path:
    return _rig_runtime_dir() / "clients"


def _startup_lock_path() -> Path:
    return _rig_runtime_dir() / "start.lock"


# ---------------------------------------------------------------------------
# Rig state (rig.json)
# ---------------------------------------------------------------------------

def read_rig_state() -> dict | None:
    """Return rig state dict if a live embedded rig exists, else None.

    Cleans up a stale rig.json if the recorded PID is no longer running.
    """
    path = _rig_json()
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        os.kill(int(state["pid"]), 0)   # raises OSError if dead
        return state
    except (KeyError, ValueError, OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None


def write_rig_state(pid: int, port: int, endpoint: str, model: str) -> None:
    path = _rig_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "pid": pid,
            "port": port,
            "endpoint": endpoint,
            "model": model,
            "started_at": time.time(),
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def _clear_rig_state() -> None:
    _rig_json().unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Client registry (one file per live CLI PID)
# ---------------------------------------------------------------------------

def register_client() -> None:
    cdir = _clients_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / str(os.getpid())).write_text(str(os.getpid()), encoding="utf-8")


def _live_client_count() -> int:
    """Count live CLI clients; prune entries whose PIDs are no longer alive."""
    cdir = _clients_dir()
    if not cdir.exists():
        return 0
    count = 0
    for entry in list(cdir.iterdir()):
        try:
            os.kill(int(entry.name), 0)
            count += 1
        except (ValueError, OSError):
            entry.unlink(missing_ok=True)
    return count


def shutdown_rig_if_last() -> None:
    """Deregister this client. If none remain, stop the embedded rig."""
    (_clients_dir() / str(os.getpid())).unlink(missing_ok=True)
    if _live_client_count() > 0:
        return
    state = read_rig_state()
    if state is None:
        return
    _kill_pid(int(state["pid"]))
    _clear_rig_state()


def _kill_pid(pid: int) -> None:
    if os.name == "nt":
        import subprocess
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        import signal as _signal
        try:
            os.kill(pid, _signal.SIGTERM)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Startup lock — prevents two CLIs racing to start the rig simultaneously.
# Uses O_CREAT|O_EXCL which is atomic on NTFS and POSIX.
# ---------------------------------------------------------------------------

class StartupLock:
    def __init__(self, timeout: float = 30.0) -> None:
        self._path = _startup_lock_path()
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> StartupLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                # Lock exists — check if holder is still alive.
                try:
                    holder = int(self._path.read_text(encoding="utf-8"))
                    os.kill(holder, 0)
                    time.sleep(0.1)         # holder alive, wait
                except (ValueError, OSError):
                    self._path.unlink(missing_ok=True)  # stale, retry
        raise SystemExit(
            "Timed out waiting for rig startup lock — another audiagentic instance may be stuck."
        )

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._path.unlink(missing_ok=True)
