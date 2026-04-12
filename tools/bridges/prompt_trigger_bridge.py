"""Standalone prompt-trigger bridge wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap: make tools.lib importable, then use robust multi-fallback root discovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.execution.jobs.prompt_trigger_bridge import run


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
