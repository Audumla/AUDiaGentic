from __future__ import annotations

import subprocess
import sys

from audiagentic.paths import REPO_ROOT


def test_check_baseline_assets_managed_headers() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "audiagentic.foundation.contracts.check_baseline_assets",
            "--check-gitignore",
            "--check-managed-headers",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
