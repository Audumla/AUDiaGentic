"""Managed npm runtime for the gpt-auto provider."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from audiagentic.foundation.paths.home import global_provider_runtime

PACKAGE = "puppeteer-core"


def runtime_dir() -> Path:
    return global_provider_runtime("gpt-auto") / "npm"


def _npm() -> str:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required for gpt-auto provider lifecycle")
    return npm


def _install(project_root=None):
    target = runtime_dir()
    target.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [_npm(), "install", "--prefix", str(target), "--no-save", PACKAGE],
        capture_output=True,
        text=True,
        check=False,
    )


def _uninstall(project_root=None):
    target = runtime_dir()
    if not target.exists():
        return subprocess.CompletedProcess(["npm", "uninstall"], 0, "", "")
    return subprocess.run(
        [_npm(), "uninstall", "--prefix", str(target), PACKAGE],
        capture_output=True,
        text=True,
        check=False,
    )


def _probe(descriptor=None):
    package = runtime_dir() / "node_modules" / "puppeteer-core"
    return {
        "available": package.is_dir(),
        "command": ["gpt-auto", "cdp"],
        "executable": str(package) if package.is_dir() else None,
        "returncode": 0 if package.is_dir() else None,
        "stdout": "" if package.is_dir() else "",
        "stderr": "" if package.is_dir() else "puppeteer-core is not installed",
    }


def node_module_path() -> Path:
    return runtime_dir() / "node_modules"
