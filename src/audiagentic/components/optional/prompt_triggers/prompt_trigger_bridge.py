"""Standalone prompt-trigger bridge wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

from audiagentic.components.optional.agent_jobs.prompt_trigger_bridge import run

if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))