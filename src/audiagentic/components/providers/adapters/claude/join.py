"""Claude Code native surface declaration for join qualification (SH55).

Claude Code 2.1.x lists its running sessions, interactive and background, with ``claude agents --json``
(pid, cwd, session id, name, idle/busy status). That listing is read-only and is the only native outside view
of a running interactive session: no prompt can be sent to it. ``claude attach`` and ``claude logs`` address
background sessions, and a Channel is an MCP server the session itself launches, available only to
subscription-signed-in sessions. ``JOIN_ADAPTER`` is the identity qualification evidence is bound to; no bridge
or extension is built here (SH41).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.session.join_readiness import JoinAdapterInfo

NATIVE_SCHEMA_VERSION = "claude-agents-json"
JOIN_ADAPTER = JoinAdapterInfo(adapter_id="claude-agents-list", adapter_version="1", native_schema_version=NATIVE_SCHEMA_VERSION)


_MAX_LISTING_BYTES = 256 * 1024
_LISTING_TIMEOUT = 8.0


def list_sessions(env: dict[str, str], cwd: Path, timeout: float = _LISTING_TIMEOUT) -> list[dict[str, Any]] | None:
    """The running sessions as ``claude agents --json`` reports them.

    None unless the command exits 0 within ``timeout`` and prints a bounded JSON list of objects; callers treat
    None as "not observed", never as an empty listing.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, scrubbed environment
            ["claude", "agents", "--json"], capture_output=True, env=env, cwd=cwd, timeout=timeout, check=False)
        if done.returncode != 0 or len(done.stdout) > _MAX_LISTING_BYTES:
            return None
        data = json.loads(done.stdout.decode(errors="replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return None
    return data
