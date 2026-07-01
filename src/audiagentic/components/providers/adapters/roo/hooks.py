"""Roo Code probe function."""
from __future__ import annotations

import shutil

from audiagentic.components.providers.adapters.probe import run_cli
from audiagentic.components.providers.services.host_capabilities import list_vscode_extensions

_EXTENSION_ID = "RooVeterinaryInc.roo-cline"


def _roo_probe(descriptor) -> dict:
    command = ["code", "--list-extensions"]
    if shutil.which("code") is None:
        return {"available": False, "command": command,
                "executable": None, "returncode": None, "stdout": "", "stderr": "code not found"}
    exts = list_vscode_extensions(allow_probe=False)
    if exts is not None:
        return {"available": _EXTENSION_ID.lower() in exts, "command": command,
                "executable": "code", "returncode": 0, "stdout": "", "stderr": ""}
    try:
        completed = run_cli(command)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "command": command, "executable": "code",
                "returncode": None, "stdout": "", "stderr": str(exc)}
    installed = _EXTENSION_ID.lower() in completed.stdout.lower()
    return {
        "available": installed,
        "command": command,
        "executable": "code",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
