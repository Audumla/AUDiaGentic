from __future__ import annotations

import os
import subprocess
import sys

from audiagentic.paths import REPO_ROOT


def test_check_baseline_assets_managed_headers() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(REPO_ROOT / "src"),
        env.get("PYTHONPATH", ""),
    ])
    env["AUDIAGENTIC_REPO_ROOT"] = str(REPO_ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.helpers.check_baseline_assets",
            "--check-gitignore",
            "--check-managed-headers",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
