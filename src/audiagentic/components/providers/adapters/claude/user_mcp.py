"""Claude user-scope MCP writes through the ``claude`` CLI.

Claude's user scope lives in its own live state file, which Claude rewrites
while it runs, so AUDiaGentic never edits that file: it reads it (through the
shared MCP JSON reader) and changes it only with ``claude mcp add-json
--scope user`` and ``claude mcp remove --scope user``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import read_raw_mcp_json

from .config import resolve_claude_user_config_path

_cli_error = make_error_factory("EXT", "CLAUDEMCP", "providers")
_TIMEOUT_SECONDS = 60


def _claude(path: Path, *args: str) -> None:
    if path != resolve_claude_user_config_path():
        raise _cli_error(1, "The claude CLI writes only the active user config file", path=str(path))
    executable = shutil.which("claude")
    if executable is None:
        raise _cli_error(2, "The claude CLI is not on PATH")
    done = subprocess.run([executable, "mcp", *args], capture_output=True, text=True,
                          timeout=_TIMEOUT_SECONDS, check=False)
    if done.returncode != 0:
        raise _cli_error(3, f"claude mcp {args[0]} failed", returncode=done.returncode,
                         stderr=done.stderr.strip()[-500:])


def _payload(entry: McpServerEntry) -> dict:
    if entry.is_remote:
        payload: dict = {"type": entry.transport or "http", "url": entry.url}
        if entry.headers:
            payload["headers"] = dict(entry.headers)
        return payload
    return {"type": "stdio", "command": entry.command, "args": list(entry.args), "env": dict(entry.env)}


def write_user_mcp(path: Path, entries: dict[str, McpServerEntry]) -> None:
    """Upsert entries: the CLI refuses to add over an existing name, so replace it."""
    existing = read_raw_mcp_json(path)
    for name, entry in entries.items():
        if name in existing:
            _claude(path, "remove", "--scope", "user", name)
        _claude(path, "add-json", "--scope", "user", name, json.dumps(_payload(entry)))


def remove_user_mcp(path: Path, name: str) -> bool:
    if name not in read_raw_mcp_json(path):
        return False
    _claude(path, "remove", "--scope", "user", name)
    return True
