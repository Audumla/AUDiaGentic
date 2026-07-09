from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from audiagentic.foundation.system.process import find_pid_on_port, kill_pid, pid_alive
from audiagentic.runtime.rig.http import probe_models_endpoint

# ---------------------------------------------------------------------------
# Internal path helpers
# ---------------------------------------------------------------------------

def _rig_runtime_dir() -> Path:
    from audiagentic.foundation.paths.home import global_harness_runtime
    return global_harness_runtime() / "rig"


def rig_start_lock():
    """The one lock serializing every rig lifecycle transition.

    Start (launch_rig_if_needed), attach (register_client), and detach/stop
    (shutdown_rig_if_last) must all hold this lock so a departing last client
    cannot kill the rig between another client's reuse decision and its
    registration (PR04 start/stop race).
    """
    from audiagentic.foundation.system.process import StartupLock

    return StartupLock(_rig_runtime_dir() / "start.lock")


def _rig_json() -> Path:
    return _rig_runtime_dir() / "rig.json"


def _clients_dir() -> Path:
    return _rig_runtime_dir() / "clients"


def _default_endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


# ---------------------------------------------------------------------------
# Rig state (rig.json)
# ---------------------------------------------------------------------------

def read_rig_state(*, expected_model: str | None = None) -> dict | None:
    """Return rig state dict if a healthy embedded rig exists, else None.

    Cleans up stale rig.json when the recorded PID is dead, the endpoint is not
    ready, or the tracked model no longer matches the requested profile.
    """
    path = _rig_json()
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        pid = int(state["pid"])
        if not pid_alive(pid):
            path.unlink(missing_ok=True)
            return None
        endpoint = str(state.get("endpoint") or _default_endpoint(int(state["port"])))
        server_model = _query_server_model(endpoint)
        if server_model is None:
            kill_pid(pid)
            path.unlink(missing_ok=True)
            return None
        if expected_model is not None and str(state.get("model")) != expected_model:
            kill_pid(pid)
            path.unlink(missing_ok=True)
            return None
        return state
    except (KeyError, ValueError, OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None


def write_rig_state(pid: int, port: int, endpoint: str, model: str) -> None:
    path = _rig_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "pid": pid,
        "port": port,
        "endpoint": endpoint,
        "model": model,
        "started_at": time.time(),
    }, indent=2) + "\n"
    # Atomic replace: a torn read would make readers unlink rig.json, leaving
    # a live rig untracked (and reapable).
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _clear_rig_state() -> None:
    _rig_json().unlink(missing_ok=True)


def _query_server_model(endpoint: str, timeout: float = 2.0) -> str | None:
    probe = probe_models_endpoint(endpoint, timeout=timeout)
    return probe.first_model_id if probe else None


def adopt_rig_state(port: int, *, endpoint: str | None = None, model: str | None = None) -> dict | None:
    """Reconstruct rig.json for a healthy rig already listening on the expected port.

    When *model* is given, adoption is refused unless the server actually
    serves it (the rig launcher registers the profile name as the served
    alias) — silently recording the requested name over a different live
    model would hand callers the wrong backend.
    """
    endpoint = endpoint or _default_endpoint(port)
    server_model = _query_server_model(endpoint)
    if server_model is None:
        return None
    if model is not None and server_model != model:
        return None

    pid = find_pid_on_port(port)
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
    state = read_rig_state(expected_model=model)
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
            if pid_alive(int(entry.name)):
                count += 1
            else:
                entry.unlink(missing_ok=True)
        except ValueError:
            entry.unlink(missing_ok=True)
    return count


def shutdown_rig_if_last(port: int | None = None) -> None:
    """Deregister this client. If none remain, stop the embedded rig.

    Deregister → count → kill happens under the same startup lock as
    launch/attach, so a concurrent client that just reused the rig (and is
    about to register) cannot lose it to a departing last client.
    """
    with rig_start_lock():
        (_clients_dir() / str(os.getpid())).unlink(missing_ok=True)
        if _live_client_count() > 0:
            return
        state = read_rig_state()
        if state is None and port is not None:
            state = adopt_rig_state(port)
        if state is None:
            return
        kill_pid(int(state["pid"]))
        _clear_rig_state()


def reap_orphan_rigs(keep_pid: int | None = None) -> list[int]:
    """Kill any running llama-server/llamafile processes not tracked by rig.json.

    Called before starting a fresh rig to prevent VRAM accumulation from sessions
    that were force-killed (SIGKILL bypasses finally blocks).
    Returns list of killed PIDs.
    """
    killed: list[int] = []
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False, timeout=10,
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
            kill_pid(pid)
            killed.append(pid)
        result2 = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llamafile.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False, timeout=10,
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
            kill_pid(pid)
            killed.append(pid)
    else:
        if shutil.which("pgrep") is None:
            return killed
        for name in ("llama-server", "llamafile"):
            try:
                result = subprocess.run(
                    ["pgrep", "-x", name],
                    capture_output=True, text=True, check=False, timeout=10,
                )
            except subprocess.TimeoutExpired:
                continue
            for line in result.stdout.splitlines():
                try:
                    pid = int(line.strip())
                except ValueError:
                    continue
                if keep_pid and pid == keep_pid:
                    continue
                kill_pid(pid)
                killed.append(pid)
    return killed
