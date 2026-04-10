"""Gemini-specific prompt-trigger bridge wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.execution.jobs.prompt_trigger_bridge import run


if __name__ == "__main__":
    raise SystemExit(run(["--provider-id", "gemini", *sys.argv[1:]]))
