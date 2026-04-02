"""Compatibility shim for moved channels CLI entrypoint."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.channels.cli.main import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
