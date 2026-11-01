"""Pi native surface declaration for join qualification (SH56).

Pi 1.x has two control surfaces: ``pi --mode rpc``, a JSONL protocol on the stdin/stdout of a process the caller
starts (``get_state``, ``prompt``, ``steer``, ``follow_up``), and the interactive TUI. Measured: a running
interactive instance opens no listening socket and exposes no attach endpoint, so the RPC protocol reaches only
a Pi process this caller owns, never a human's running session. ``JOIN_ADAPTER`` is the identity qualification
evidence is bound to; no bridge or extension is built here (SH41).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.session.join_readiness import JoinAdapterInfo

NATIVE_SCHEMA_VERSION = "pi-rpc-jsonl"
JOIN_ADAPTER = JoinAdapterInfo(adapter_id="pi-rpc", adapter_version="1", native_schema_version=NATIVE_SCHEMA_VERSION)


def rpc_get_state(env: dict[str, str], cwd: Path, timeout: float = 20.0) -> dict[str, Any] | None:
    """Ask an owned ``pi --mode rpc`` child for its state; None when it does not answer in time."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, scrubbed environment
            ["pi", "--mode", "rpc", "--offline", "--no-extensions", "--no-mcp", "--no-session"],
            input=b'{"type":"get_state"}\n', capture_output=True, env=env, cwd=cwd, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    for line in done.stdout.decode(errors="replace").splitlines():
        try:
            reply = json.loads(line)
        except ValueError:
            continue
        if reply.get("command") == "get_state" and reply.get("success"):
            return dict(reply.get("data") or {})
    return None
