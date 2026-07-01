"""Qwen probe function."""
from __future__ import annotations

import shutil

from audiagentic.components.providers.adapters.probe import run_cli


def _qwen_probe(_descriptor) -> dict:
    command = ["qwen", "--version"]
    executable = shutil.which("qwen")
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        completed = run_cli(command)
        if completed.returncode == 0:
            return {
                "available": True,
                "command": command,
                "executable": executable,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": True,
        "command": command,
        "executable": executable,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
