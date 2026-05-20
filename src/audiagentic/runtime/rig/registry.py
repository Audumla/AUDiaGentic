from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Internal path helpers
# ---------------------------------------------------------------------------

def _rig_runtime_dir() -> Path:
    from audiagentic.runtime.home import global_harness_runtime
    return global_harness_runtime() / "rig"


def _rig_json() -> Path:
    return _rig_runtime_dir() / "rig.json"


def _clients_dir() -> Path:
    return _rig_runtime_dir() / "clients"


def _startup_lock_path() -> Path:
    return _rig_runtime_dir() / "start.lock"


def _default_endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


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


def _query_server_model(endpoint: str, timeout: float = 2.0) -> str | None:
    try:
        with urlopen(f"{endpoint}/models", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read())
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None

    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])
    models = payload.get("models")
    if isinstance(models, list) and models:
        first = models[0]
        if isinstance(first, dict) and first.get("model"):
            return str(first["model"])
        if isinstance(first, dict) and first.get("name"):
            return str(first["name"])
    return None


def _find_pid_listening_on_port(port: int) -> int | None:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        needle = f":{port}"
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if "LISTENING" not in stripped or needle not in stripped:
                continue
            parts = stripped.split()
            if len(parts) < 5:
                continue
            local_addr = parts[1]
            state = parts[3]
            if not local_addr.endswith(needle) or state != "LISTENING":
                continue
            try:
                return int(parts[4])
            except ValueError:
                continue
        return None

    for command in (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["ss", "-ltnp"],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            continue
        if command[0] == "lsof":
            for line in result.stdout.splitlines():
                try:
                    return int(line.strip())
                except ValueError:
                    continue
            continue
        needle = f":{port} "
        for line in result.stdout.splitlines():
            if needle not in line:
                continue
            marker = "pid="
            idx = line.find(marker)
            if idx == -1:
                continue
            fragment = line[idx + len(marker):].split(",", 1)[0]
            try:
                return int(fragment)
            except ValueError:
                continue
    return None


def adopt_rig_state(port: int, *, endpoint: str | None = None, model: str | None = None) -> dict | None:
    """Reconstruct rig.json for a healthy rig already listening on the expected port."""
    endpoint = endpoint or _default_endpoint(port)
    server_model = _query_server_model(endpoint)
    if server_model is None:
        return None

    pid = _find_pid_listening_on_port(port)
    if pid is None:
        return None

    write_rig_state(pid, port, endpoint, model or server_model)
    return {
        "pid": pid,
        "port": port,
        "endpoint": endpoint,
        "model": model or server_model,
    }


def ensure_rig_state(port: int, *, model: str | None = None) -> dict | None:
    """Return live rig state, rebuilding rig.json from active port when needed."""
    state = read_rig_state()
    if state is not None:
        return state
    return adopt_rig_state(port, model=model)


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


def shutdown_rig_if_last(port: int | None = None) -> None:
    """Deregister this client. If none remain, stop the embedded rig."""
    (_clients_dir() / str(os.getpid())).unlink(missing_ok=True)
    if _live_client_count() > 0:
        return
    state = read_rig_state()
    if state is None and port is not None:
        state = adopt_rig_state(port)
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


def reap_orphan_rigs(keep_pid: int | None = None) -> list[int]:
    """Kill any running llama-server/llamafile processes not tracked by rig.json.

    Called before starting a fresh rig to prevent VRAM accumulation from sessions
    that were force-killed (SIGKILL bypasses finally blocks).
    Returns list of killed PIDs.
    """
    killed: list[int] = []
    if os.name == "nt":
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().strip('"').split('","')
            if not parts or len(parts) < 2:
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            if keep_pid and pid == keep_pid:
                continue
            _kill_pid(pid)
            killed.append(pid)
        # Also check llamafile
        result2 = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llamafile.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
        )
        for line in result2.stdout.splitlines():
            parts = line.strip().strip('"').split('","')
            if not parts or len(parts) < 2:
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            if keep_pid and pid == keep_pid:
                continue
            _kill_pid(pid)
            killed.append(pid)
    else:
        import subprocess
        for name in ("llama-server", "llamafile"):
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True, text=True, check=False,
            )
            for line in result.stdout.splitlines():
                try:
                    pid = int(line.strip())
                except ValueError:
                    continue
                if keep_pid and pid == keep_pid:
                    continue
                _kill_pid(pid)
                killed.append(pid)
    return killed


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
