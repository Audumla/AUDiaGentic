"""Sandbox helpers for destructive tests."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import tools.misc.create_sandbox as create_sandbox


@dataclass
class Sandbox:
    root: Path
    repo: Path
    logs: Path
    artifacts: Path

    def cleanup(self) -> None:
        if os.getenv("KEEP_FAILED_SANDBOX") == "1":
            return
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def create(temp_root: Path, test_id: str) -> Sandbox:
    paths = create_sandbox.create_sandbox(temp_root, test_id)
    return Sandbox(
        root=paths.root,
        repo=paths.repo,
        logs=paths.logs,
        artifacts=paths.artifacts,
    )
