from __future__ import annotations

import json
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

from audiagentic.runtime.rig.http import probe_models_endpoint


_LLAMA_ARG_MAP: list[tuple[str, str, str]] = [
    ("context_size", "--ctx-size", "value"),
]

_LLAMA_ARG_KEYS = {key for key, _, _ in _LLAMA_ARG_MAP}


def resolve_platform_dirs(bin_dir: Path) -> tuple[Path, Path]:
    if sys.platform == "win32":
        return bin_dir / "llama-server" / "windows", bin_dir / "llamafile" / "windows"
    if sys.platform == "darwin":
        return bin_dir / "llama-server" / "macOS", bin_dir / "llamafile" / "macOS"
    return bin_dir / "llama-server" / "linux", bin_dir / "llamafile" / "linux"


def executable_command(binary: Path) -> list[str]:
    if sys.platform == "win32":
        return [str(binary)]
    try:
        if binary.read_bytes()[:2] == b"MZ":
            return ["sh", str(binary)]
    except OSError:
        pass
    return [str(binary)]


def choose_free_port(host: str) -> int:
    candidates = list(range(30000, 61000))
    random.shuffle(candidates)
    for port in candidates[:64]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"Unable to find free port on {host}")


def candidate_ports(host: str, requested_port: int) -> list[int]:
    if requested_port != 0:
        return [requested_port]
    primary = choose_free_port(host)
    extras = []
    seen = {primary}
    while len(extras) < 7:
        port = choose_free_port(host)
        if port in seen:
            continue
        seen.add(port)
        extras.append(port)
    return [primary, *extras]


def build_command(
    binary: Path,
    model_arg: str,
    host: str,
    port: int,
    device: str | None,
    server_cfg: dict[str, object],
    chat_template_kwargs: dict[str, object],
    alias: str | None = None,
) -> list[str]:
    args: list[str] = []
    if binary.name.startswith("llamafile"):
        args.append("--server")
    args.extend(["--host", host, "--port", str(port), "--model", model_arg])
    if alias:
        args.extend(["--alias", alias])
    if device:
        args.extend(["--device", device])
    for key, flag, kind in _LLAMA_ARG_MAP:
        val = server_cfg.get(key)
        if val is None:
            continue
        if kind == "value":
            args.extend([flag, str(val)])
        elif kind == "flag" and val:
            args.append(flag)
    for key, val in server_cfg.items():
        if key in _LLAMA_ARG_KEYS or val is None:
            continue
        flag = f"--{key.replace('_', '-')}"
        if isinstance(val, bool):
            if val:
                args.append(flag)
            continue
        args.extend([flag, str(val)])
    if chat_template_kwargs:
        args.extend(["--chat-template-kwargs", json.dumps(chat_template_kwargs, separators=(",", ":"))])
    return [*executable_command(binary), *args]


def wait_for_health(
    base_url: str,
    timeout_s: float,
    *,
    process: subprocess.Popen[bytes] | None = None,
    log_path: Path | None = None,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = "unknown error"
    while time.monotonic() < deadline:
        probe = probe_models_endpoint(base_url, timeout=5)
        if probe is not None:
            return
        if process is not None and process.poll() is not None:
            detail = f"Rig exited early with code {process.returncode}"
            if log_path is not None:
                detail += f". See log: {log_path}"
            raise SystemExit(detail)
        time.sleep(0.5)
    raise SystemExit(f"Rig health check failed for {base_url}/models: {last_error}")
