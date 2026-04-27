#!/usr/bin/env python3
"""Project-local launcher for the AUDiaGentic planning MCP server.

This wrapper keeps the MCP config project-specific and portable by resolving the
repository root from this file location at runtime instead of depending on the
client's process cwd.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch AUDiaGentic planning MCP server")
    parser.add_argument(
        "--root",
        type=Path,
        help="Project root directory (takes precedence over AUDIAGENTIC_ROOT env var)",
    )
    args = parser.parse_args()

    here = Path(__file__).resolve()
    project_root = here.parents[3]

    if args.root:
        target_root = args.root.resolve()
    elif os.environ.get("AUDIAGENTIC_ROOT"):
        target_root = Path(os.environ["AUDIAGENTIC_ROOT"]).resolve()
    else:
        target_root = project_root

    os.environ["AUDIAGENTIC_ROOT"] = str(target_root)
    os.chdir(project_root)

    for candidate in (project_root, project_root / "src"):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)

    server_path = (
        project_root / "tools" / "mcp" / "audiagentic-planning" / "audiagentic_planning_mcp_v2.py"
    )
    runpy.run_path(str(server_path), run_name="__main__")


if __name__ == "__main__":
    main()
