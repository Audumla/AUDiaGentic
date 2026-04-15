from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_check_baseline_assets_managed_headers() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/checks/check_baseline_assets.py",
            "--check-gitignore",
            "--check-managed-headers",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
