"""Minimal MCP server preflight diagnostics.

AUDiaGentic never spawns configured MCP servers during a live harness session
-- the harness (pi/opencode) does, so a generic "-32001"/"server unavailable"
error surfacing inside a live session is opaque to us from the outside.

This module provides a self-test instead: spawn a configured server the same
way the harness would, complete the MCP ``initialize`` handshake ourselves,
and report whether it started, how long it took, and (if it didn't) why.
Deliberately small -- one entry point, no protocol layer beyond
``initialize``, no dataclass hierarchy. Extend only if a concrete future need
(tool-call-phase probing, stderr capture, etc.) shows up.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from audiagentic.foundation.system.supervised_process import spawn_supervised

_INITIALIZE_ID = 1


def _initialize_request() -> str:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": _INITIALIZE_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "audiagentic-mcp-diagnostics", "version": "1"},
                },
            }
        )
        + "\n"
    )


def probe_mcp_server(
    name: str,
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Spawn *command*, attempt the MCP initialize handshake, report the result.

    Returns a small, redaction-safe dict -- the raw command/env are never
    included, only the *name* the caller already supplied. Fields:

    - ``server_name``, ``ok``, ``phase`` (currently always ``"initialization"``
      -- this probe only exercises startup, not a live tool call),
      ``elapsed_ms``.
    - On failure only: ``exit_status`` (when the process exited) and
      ``error``, a stable class: ``"spawn-failed"``, ``"initialize-timeout"``,
      ``"initialize-rejected"``, or ``"crashed"``.
    """
    start = time.monotonic()
    try:
        owned = spawn_supervised(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return {
            "server_name": name,
            "ok": False,
            "phase": "initialization",
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "error": "spawn-failed",
        }

    try:
        if owned.stdin is not None:
            try:
                owned.stdin.write(_initialize_request())
                owned.stdin.flush()
            except (OSError, ValueError):
                pass

        line_queue: queue.Queue[str | None] = queue.Queue(maxsize=1)

        def _read_line() -> None:
            try:
                line = owned.stdout.readline() if owned.stdout is not None else None
            except (OSError, ValueError):
                line = None
            line_queue.put(line)

        reader = threading.Thread(target=_read_line, daemon=True)
        reader.start()
        try:
            line = line_queue.get(timeout=timeout)
            timed_out = False
        except queue.Empty:
            line = None
            timed_out = True

        elapsed_ms = round((time.monotonic() - start) * 1000)

        if timed_out:
            return {
                "server_name": name,
                "ok": False,
                "phase": "initialization",
                "elapsed_ms": elapsed_ms,
                "exit_status": owned.poll(),
                "error": "initialize-timeout",
            }

        if not line:
            exit_status = owned.poll()
            if exit_status is None:
                try:
                    exit_status = owned.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    exit_status = None
            return {
                "server_name": name,
                "ok": False,
                "phase": "initialization",
                "elapsed_ms": elapsed_ms,
                "exit_status": exit_status,
                "error": "crashed",
            }

        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            return {
                "server_name": name,
                "ok": False,
                "phase": "initialization",
                "elapsed_ms": elapsed_ms,
                "error": "initialize-rejected",
            }

        if response.get("id") == _INITIALIZE_ID and "result" in response:
            return {
                "server_name": name,
                "ok": True,
                "phase": "initialization",
                "elapsed_ms": elapsed_ms,
            }

        return {
            "server_name": name,
            "ok": False,
            "phase": "initialization",
            "elapsed_ms": elapsed_ms,
            "error": "initialize-rejected",
        }
    finally:
        owned.close()


__all__ = ["probe_mcp_server"]
