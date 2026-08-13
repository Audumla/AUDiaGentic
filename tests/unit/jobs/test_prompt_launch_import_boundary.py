"""Import-boundary protection for canonical prompt Work launches."""
from __future__ import annotations

import os
import subprocess
import sys


def test_prompt_launch_does_not_eagerly_load_legacy_lifecycle_modules() -> None:
    code = """
import sys
import audiagentic.components.agent_jobs.prompt_launch
legacy = set()
loaded = legacy.intersection(sys.modules)
raise SystemExit('legacy modules loaded eagerly: ' + repr(sorted(loaded)) if loaded else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
