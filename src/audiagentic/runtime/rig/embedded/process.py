from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.system.process import executable_command
from audiagentic.runtime.rig.http import probe_models_endpoint

_LLAMA_ARG_MAP: list[tuple[str, str, str]] = [
    ("context_size", "--ctx-size", "value"),
]

_LLAMA_ARG_KEYS = {key for key, _, _ in _LLAMA_ARG_MAP}


def _process_error(prefix: str, code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix=prefix,
        component="RIGPROC",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def resolve_platform_dirs(bin_dir: Path) -> tuple[Path, Path]:
    if sys.platform == "win32":
        return bin_dir / "llama-server" / "windows", bin_dir / "llamafile" / "windows"
    if sys.platform == "darwin":
        return bin_dir / "llama-server" / "macOS", bin_dir / "llamafile" / "macOS"
    return bin_dir / "llama-server" / "linux", bin_dir / "llamafile" / "linux"


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
    while time.monotonic() < deadline:
        probe = probe_models_endpoint(base_url, timeout=5)
        if probe is not None:
            return
        if process is not None and process.poll() is not None:
            detail = f"Rig exited early with code {process.returncode}"
            if log_path is not None:
                detail += f". See log: {log_path}"
            raise _process_error(
                "EXT",
                1,
                detail,
                returncode=process.returncode,
                log_path=str(log_path) if log_path is not None else None,
            )
        time.sleep(0.5)
    raise _process_error("TO", 2, f"Rig health check failed for {base_url}/models", base_url=base_url)
