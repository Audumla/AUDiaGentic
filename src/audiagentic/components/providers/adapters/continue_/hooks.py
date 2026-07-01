"""Continue probe function."""
from __future__ import annotations

import shutil


def _continue_probe(_descriptor) -> dict:
    command = ["cn", "--version"]
    executable = shutil.which("cn")
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    return {
        "available": True,
        "command": command,
        "executable": executable,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
